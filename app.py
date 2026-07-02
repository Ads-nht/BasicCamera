import os
import re
import asyncio
import logging
import io
import shutil
import mimetypes
import datetime
import fcntl
import glob
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse, FileResponse
from pydantic import BaseModel

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("camera-app")

app = FastAPI(
    title="Basic Camera Manager API",
    description="Backend API to manage, stream, and backup media from Nikon DSC Coolpix S2900 over PTP",
    version="1.0.0"
)

@app.get("/", response_class=HTMLResponse)
async def get_index():
    """Serves the main dashboard user interface."""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Failed to read index.html: {e}")
        return HTMLResponse(content=f"<h2>UI Files Missing</h2><p>{str(e)}</p>", status_code=404)

# ==============================================================================
# CONFIGURATION & GLOBAL STATE
# ==============================================================================
# Determine storage root dynamically (inside docker volume vs local host development)
if os.path.exists("/storage") and os.access("/storage", os.W_OK):
    BACKUP_DIR = "/storage/backup"
    CACHE_THUMB_DIR = "/storage/backup/.cache/thumbnails"
else:
    BACKUP_DIR = os.path.abspath("./storage")
    CACHE_THUMB_DIR = os.path.abspath("./storage/.cache/thumbnails")

SECURE_DELETE_TOKEN = os.getenv("SECURE_DELETE_TOKEN", "CONFIRM_DELETE_COOLPIX")

# Serialization lock: Prevents concurrent operations from flooding the camera PTP buffer
camera_lock = asyncio.Lock()

# Global dictionary to track backup progress/state
backup_status: Dict[str, Any] = {
    "active": False,
    "total_files": 0,
    "completed_files": 0,
    "current_file": "",
    "errors": []
}

# Global in-memory camera catalog cache
active_files_catalog: Dict[int, Dict[str, Any]] = {}
os.makedirs(CACHE_THUMB_DIR, exist_ok=True)
pre_cache_active = False

class CameraSession:
    def __init__(self):
        self.camera = None
        
    def _init_local(self):
        import gphoto2 as gp
        self.camera = gp.Camera()
        self.camera.init()
        
    def _close_local(self):
        if self.camera:
            try:
                self.camera.exit()
            except:
                pass
            self.camera = None

    async def get_preview(self, folder: str, name: str) -> bytes:
        """Gets preview bytes using the persistent camera session, auto-recovering on failures."""
        def fetch():
            import gphoto2 as gp
            if not self.camera:
                logger.info("Initializing persistent camera session...")
                self._init_local()
            camera_file = gp.CameraFile()
            self.camera.file_get(folder, name, gp.GP_FILE_TYPE_PREVIEW, camera_file)
            return bytes(camera_file.get_data_and_size())
            
        try:
            return await asyncio.to_thread(fetch)
        except Exception as e:
            logger.warning(f"Session preview fetch failed: {e}. Resetting session and retrying...")
            await asyncio.to_thread(self._close_local)
            # Try to recover the USB connection dynamically
            reset_camera_usb()
            await asyncio.sleep(1.0)
            return await asyncio.to_thread(fetch)

camera_session = CameraSession()

async def fetch_preview_bytes(folder: str, name: str) -> bytes:
    """Fetches the preview/thumbnail bytes of a camera file."""
    remote_host = os.getenv("REMOTE_CAMERA_HOST")
    if remote_host:
        # Run python code remotely over SSH
        preview_script = f"""
import gphoto2 as gp, sys
camera = gp.Camera()
camera.init()
try:
    camera_file = gp.CameraFile()
    camera.file_get("{folder}", "{name}", gp.GP_FILE_TYPE_PREVIEW, camera_file)
    sys.stdout.buffer.write(camera_file.get_data_and_size())
finally:
    camera.exit()
"""
        process = await asyncio.create_subprocess_exec(
            "ssh", f"ads@{remote_host}", "docker", "exec", "camera-app", "python3", "-c", preview_script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise Exception(f"Remote preview fetch failed: {stderr.decode()}")
        return stdout
    else:
        # Run locally with persistent session
        return await camera_session.get_preview(folder, name)

pre_cache_active = False

async def pre_cache_thumbnails(files: List[dict]):
    global pre_cache_active
    if pre_cache_active:
        return
    pre_cache_active = True
    logger.info("Starting background thumbnail pre-caching...")
    try:
        for f in files:
            if not await is_camera_connected():
                break
                
            cache_filename = f"{f['name']}_{f['size'].replace(' ', '_')}.jpg"
            cache_path = os.path.join(CACHE_THUMB_DIR, cache_filename)
            
            if os.path.exists(cache_path):
                continue
                
            async with camera_lock:
                try:
                    data = await fetch_preview_bytes(f["folder"], f["name"])
                    if len(data) > 0:
                        with open(cache_path, "wb") as thumb_f:
                            thumb_f.write(data)
                        logger.info(f"Cached thumbnail for {f['name']}")
                except Exception as ex:
                    logger.error(f"Failed to cache thumbnail for {f['name']}: {ex}")
            # Yield lock window to prioritize other API requests
            await asyncio.sleep(0.05)
    finally:
        pre_cache_active = False
        logger.info("Background thumbnail pre-caching complete.")

# ==============================================================================
# CUSTOM EXCEPTIONS
# ==============================================================================
class CameraConnectionError(Exception):
    """Raised when the camera is disconnected, busy, or uncommunicative."""
    pass

# ==============================================================================
# PARSING UTILITIES
# ==============================================================================
def parse_gphoto_file_list(stdout: str) -> List[Dict[str, Any]]:
    """
    Parses the output of 'gphoto2 --list-files'.
    Handles varying column configurations (like resolution column in photos and UNIX timestamps at the end of lines).
    """
    files = []
    current_folder = "/"
    folder_pattern = re.compile(r"in folder '([^']+)'")
    
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
            
        folder_match = folder_pattern.search(line)
        if folder_match:
            current_folder = folder_match.group(1)
            continue
            
        if line.startswith("#"):
            parts = line.split()
            if len(parts) >= 5: # Minimal columns: #index, filename, status, size_val, size_unit
                index_str = parts[0].lstrip("#")
                if not index_str.isdigit():
                    continue
                index = int(index_str)
                name = parts[1]
                
                # Retrieve mimetype by scanning columns containing '/'
                mime = None
                for p in parts:
                    if "/" in p:
                        mime = p
                        break
                if not mime:
                    # Fallback if mimetype lacks a slash
                    if parts[-1].isdigit() and len(parts) > 5:
                        mime = parts[-2]
                    else:
                        mime = parts[-1]
                
                # Size is parts[3] (value) + " " + parts[4] (unit, e.g. "KB")
                size = f"{parts[3]} {parts[4]}"
                
                files.append({
                    "index": index,
                    "name": name,
                    "folder": current_folder,
                    "path": f"{current_folder}/{name}" if current_folder != "/" else f"/{name}",
                    "size": size,
                    "mime": mime
                })
                
    return files

# ==============================================================================
# SAFE EXECUTION CORE (POKA-YOKE FOR I/O CONFLICTS)
# ==============================================================================
def reset_camera_usb() -> bool:
    """
    Scans host sysfs (locally or remotely over SSH) to find the Nikon camera
    and performs a low-level USB bus reset via ioctl.
    """
    remote_host = os.getenv("REMOTE_CAMERA_HOST")
    if remote_host:
        logger.info(f"Attempting remote low-level USB bus reset on host {remote_host}...")
        reset_code = """
import glob, os, fcntl
for dev_path in glob.glob('/sys/bus/usb/devices/*'):
    id_vendor_path = os.path.join(dev_path, 'idVendor')
    id_product_path = os.path.join(dev_path, 'idProduct')
    if os.path.exists(id_vendor_path) and os.path.exists(id_product_path):
        try:
            with open(id_vendor_path, 'r') as f: vendor = f.read().strip()
            with open(id_product_path, 'r') as f: product = f.read().strip()
            if vendor == '04b0' and product == '035e':
                with open(os.path.join(dev_path, 'busnum'), 'r') as f: bus = f.read().strip().zfill(3)
                with open(os.path.join(dev_path, 'devnum'), 'r') as f: dev = f.read().strip().zfill(3)
                usb_device_path = f'/dev/bus/usb/{bus}/{dev}'
                if os.path.exists(usb_device_path):
                    with open(usb_device_path, 'wb') as usb_f:
                        fcntl.ioctl(usb_f.fileno(), 21780, 0)
                    print('RESET_SUCCESS')
        except Exception as e:
            print(f'RESET_FAIL: {e}')
"""
        import subprocess
        try:
            cmd = ["ssh", f"ads@{remote_host}", "docker", "exec", "camera-app", "python3", "-c", reset_code]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()
            if "RESET_SUCCESS" in out:
                logger.info("Successfully triggered remote camera USB reset over SSH.")
                return True
        except Exception as e:
            logger.error(f"Failed to trigger remote USB reset over SSH: {e}")
        return False

    logger.info("Attempting local low-level USB bus reset for Nikon camera...")
    found = False
    for dev_path in glob.glob("/sys/bus/usb/devices/*"):
        id_vendor_path = os.path.join(dev_path, "idVendor")
        id_product_path = os.path.join(dev_path, "idProduct")
        if os.path.exists(id_vendor_path) and os.path.exists(id_product_path):
            try:
                with open(id_vendor_path, 'r') as f:
                    vendor = f.read().strip()
                with open(id_product_path, 'r') as f:
                    product = f.read().strip()
                
                if vendor == "04b0" and product == "035e":
                    with open(os.path.join(dev_path, "busnum"), 'r') as f:
                        bus = f.read().strip().zfill(3)
                    with open(os.path.join(dev_path, "devnum"), 'r') as f:
                        dev = f.read().strip().zfill(3)
                    
                    usb_device_path = f"/dev/bus/usb/{bus}/{dev}"
                    if os.path.exists(usb_device_path):
                        # 21780 represents USBDEVFS_RESET ioctl
                        with open(usb_device_path, 'wb') as usb_f:
                            fcntl.ioctl(usb_f.fileno(), 21780, 0)
                        logger.info(f"Successfully sent USBDEVFS_RESET ioctl to {usb_device_path}")
                        found = True
                        break
            except Exception as e:
                logger.error(f"Failed to reset Nikon USB device: {e}")
    return found

async def execute_gphoto_raw(args: List[str]) -> tuple[str, str, int]:
    """Runs a raw gphoto2 command asynchronously (locally or remotely via SSH), with auto-reset retry."""
    remote_host = os.getenv("REMOTE_CAMERA_HOST")
    if remote_host:
        cmd = "ssh"
        cmd_args = [f"ads@{remote_host}", "docker", "exec", "camera-app", "gphoto2"] + args
    else:
        cmd = "gphoto2"
        cmd_args = args

    async def run_once():
        try:
            process = await asyncio.create_subprocess_exec(
                cmd, *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            return (
                stdout.decode("utf-8", errors="ignore"),
                stderr.decode("utf-8", errors="ignore"),
                process.returncode
            )
        except Exception as e:
            return "", str(e), -1

    stdout, stderr, code = await run_once()
    
    # If connection failure detected, perform USB reset and retry once
    err_lower = stderr.lower()
    if code != 0 and any(k in err_lower for k in ["timeout", "busy", "could not claim", "claim interface"]):
        logger.warning(f"gphoto2 failed with connection error: {stderr.strip()}. Triggering USB reset recovery...")
        if reset_camera_usb():
            await asyncio.sleep(2.0) # Wait for re-enumeration
            logger.info("Retrying gphoto2 command after USB reset...")
            stdout, stderr, code = await run_once()
            
    return stdout, stderr, code

async def is_camera_connected() -> bool:
    """Fast, safe connection check without locking the execution queue."""
    stdout, stderr, code = await execute_gphoto_raw(["--auto-detect"])
    if code != 0 or "Error" in stderr or "Error" in stdout:
        return False
    # Output contains headers + separator + device list. Must have >= 3 non-empty lines to indicate device detection.
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    return len(lines) >= 3

async def execute_gphoto_safe(args: List[str]) -> str:
    """
    Executes a gphoto2 command while holding the lock.
    Raises CameraConnectionError if the camera is unplugged or busy.
    """
    async with camera_lock:
        if not await is_camera_connected():
            raise CameraConnectionError("Camera is disconnected.")
            
        stdout, stderr, code = await execute_gphoto_raw(args)
        
        # Check for typical libgphoto2 connection failure strings
        if code != 0 or "Error" in stderr or "Could not find" in stderr or "Could not claim" in stderr:
            logger.error(f"gphoto2 execution failed (code: {code}): {stderr.strip()}")
            raise CameraConnectionError(f"Camera connection lost or busy: {stderr.strip()}")
            
        return stdout

# ==============================================================================
# BACKGROUND WORKER FOR MEDIATED BACKUPS
# ==============================================================================
async def backup_worker(indices: List[int], target_dir: str):
    """Background task that safely copies files file-by-file to persistent disk."""
    global backup_status
    backup_status["active"] = True
    backup_status["total_files"] = len(indices)
    backup_status["completed_files"] = 0
    backup_status["errors"] = []
    
    os.makedirs(target_dir, exist_ok=True)
    
    try:
        # Retrieve latest file registry to match index to names
        stdout = await execute_gphoto_safe(["--list-files"])
        camera_files = parse_gphoto_file_list(stdout)
        file_map = {f["index"]: f for f in camera_files}
    except Exception as e:
        backup_status["errors"].append(f"Failed to fetch camera catalog: {e}")
        backup_status["active"] = False
        return
        
    for idx in indices:
        if idx not in file_map:
            backup_status["errors"].append(f"File index {idx} not found on camera.")
            continue
            
        file_info = file_map[idx]
        filename = file_info["name"]
        backup_status["current_file"] = filename
        
        local_filepath = os.path.join(target_dir, filename)
        
        # Acquire lock only during file transfer
        async with camera_lock:
            try:
                if not await is_camera_connected():
                    raise CameraConnectionError("Camera disconnected.")
                    
                # Download single file directly to persistent host disk
                process = await asyncio.create_subprocess_exec(
                    "gphoto2", "--get-file", str(idx), "--filename", local_filepath,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                _, stderr = await process.communicate()
                
                if process.returncode != 0:
                    raise Exception(stderr.decode().strip())
                    
                backup_status["completed_files"] += 1
                logger.info(f"Successfully backed up {filename} to {local_filepath}")
            except Exception as e:
                err_msg = f"Failed to transfer file {filename} (Index {idx}): {e}"
                logger.error(err_msg)
                backup_status["errors"].append(err_msg)
                if isinstance(e, CameraConnectionError) or "disconnected" in str(e).lower():
                    backup_status["errors"].append("Backup worker aborted due to camera disconnect.")
                    break
                    
    backup_status["active"] = False
    backup_status["current_file"] = ""

# ==============================================================================
# API REQUEST MODELS
# ==============================================================================
class BackupRequest(BaseModel):
    indices: Optional[List[int]] = None
    all: bool = False

class DeleteRequest(BaseModel):
    indices: List[int]
    confirm: bool
    token: str

# ==============================================================================
# ENDPOINTS
# ==============================================================================

@app.exception_handler(CameraConnectionError)
async def camera_connection_exception_handler(request, exc):
    """Gracefully captures connection breaks and returns standardized JSON state."""
    return JSONResponse(
        status_code=503,
        content={"status": "camera_disconnected", "detail": str(exc)}
    )

@app.get("/api/status")
async def get_status():
    """Diagnostic endpoint checking physical camera status."""
    connected = await is_camera_connected()
    return {
        "status": "connected" if connected else "disconnected",
        "lock_engaged": camera_lock.locked(),
        "backup_running": backup_status["active"]
    }

@app.get("/api/files")
async def list_files(background_tasks: BackgroundTasks):
    """Lists all files on the digital camera."""
    global active_files_catalog
    # If the lock is busy and we already have a cached list, serve it immediately to avoid blocking
    if camera_lock.locked() and active_files_catalog:
        return {
            "status": "success",
            "count": len(active_files_catalog),
            "files": list(active_files_catalog.values())
        }
        
    stdout = await execute_gphoto_safe(["--list-files"])
    files = parse_gphoto_file_list(stdout)
    active_files_catalog = {f["index"]: f for f in files}
    
    # Start pre-caching thumbnails in the background
    background_tasks.add_task(pre_cache_thumbnails, files)
    
    return {
        "status": "success",
        "count": len(files),
        "files": files
    }

@app.get("/api/files/{index}/preview")
async def get_file_preview(index: int):
    """Fetches a fast, screen-size JPEG preview (640x480) of a media asset, checking disk caches first."""
    global active_files_catalog
    if not active_files_catalog:
        try:
            stdout = await execute_gphoto_safe(["--list-files"])
            files = parse_gphoto_file_list(stdout)
            active_files_catalog = {f["index"]: f for f in files}
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Camera not ready: {str(e)}")
            
    file_info = active_files_catalog.get(index)
    if not file_info:
        raise HTTPException(status_code=404, detail=f"File with index {index} not found.")
        
    folder = file_info["folder"]
    name = file_info["name"]
    
    # 1. Cache-first check (shared with thumbnail cache filename!)
    cache_filename = f"{name}_{file_info['size'].replace(' ', '_')}.jpg"
    cache_path = os.path.join(CACHE_THUMB_DIR, cache_filename)
    
    if os.path.exists(cache_path):
        logger.info(f"Serving preview for {name} directly from disk cache.")
        return FileResponse(cache_path, media_type="image/jpeg")
        
    # 2. Check if the original file is already backed up locally
    local_filepath = os.path.join(BACKUP_DIR, name)
    if os.path.exists(local_filepath):
        try:
            def generate_local_preview():
                from PIL import Image
                if name.lower().endswith(('.jpg', '.jpeg', '.png', '.nef')):
                    with Image.open(local_filepath) as img:
                        img.thumbnail((640, 480))
                        img.convert("RGB").save(cache_path, "JPEG")
                    return True
                return False
                
            success = await asyncio.to_thread(generate_local_preview)
            if success and os.path.exists(cache_path):
                logger.info(f"Generated and served preview for {name} from local backup file.")
                return FileResponse(cache_path, media_type="image/jpeg")
        except Exception as e:
            logger.warning(f"Failed to generate local preview from backup for {name}: {e}")
            
    # 3. Cache miss: Fetch from camera and store to cache
    if await is_camera_connected():
        async with camera_lock:
            try:
                data = await fetch_preview_bytes(folder, name)
                if len(data) > 0:
                    with open(cache_path, "wb") as thumb_f:
                        thumb_f.write(data)
                    return Response(content=data, media_type="image/jpeg")
            except Exception as ex:
                logger.error(f"Failed to fetch preview for index {index}: {ex}")
                
    raise HTTPException(status_code=500, detail="Failed to retrieve preview from camera.")

@app.get("/api/files/{index}/stream")
async def stream_file(index: int):
    """Streams a media asset from local disk backup if available, otherwise directly from camera."""
    global active_files_catalog
    
    file_info = active_files_catalog.get(index)
    if file_info:
        name = file_info["name"]
        local_filepath = os.path.join(BACKUP_DIR, name)
        if os.path.exists(local_filepath):
            logger.info(f"Serving stream for {name} directly from local disk cache.")
            return FileResponse(local_filepath, media_type="application/octet-stream", filename=name)
            
    if not await is_camera_connected():
        raise CameraConnectionError("Camera is disconnected.")
        
    async def chunk_generator():
        # Keep lock active throughout the stream session
        async with camera_lock:
            process = await asyncio.create_subprocess_exec(
                "gphoto2", "--get-file", str(index), "--stdout",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                # 64KB streaming blocks
                while True:
                    chunk = await process.stdout.read(65536)
                    if not chunk:
                        break
                    yield chunk
            except Exception as e:
                logger.error(f"Streaming error on file index {index}: {e}")
                try:
                    process.kill()
                except:
                    pass
            finally:
                await process.wait()
                if process.returncode != 0:
                    stderr_err = await process.stderr.read()
                    logger.error(f"Streaming subprocess exited with error: {stderr_err.decode().strip()}")

    return StreamingResponse(chunk_generator(), media_type="application/octet-stream")

@app.post("/api/backup")
async def trigger_backup(payload: BackupRequest, background_tasks: BackgroundTasks):
    """Triggers background copy of camera media to local disk backup."""
    if backup_status["active"]:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Backup job already running."})
        
    # Gather target indices
    if payload.all:
        stdout = await execute_gphoto_safe(["--list-files"])
        files = parse_gphoto_file_list(stdout)
        indices = [f["index"] for f in files]
    else:
        if not payload.indices:
            raise HTTPException(status_code=400, detail="Must provide indices or set 'all' to true.")
        indices = payload.indices
        
    if not indices:
        return {"status": "success", "message": "No files to backup."}
        
    # Queue worker in the background
    background_tasks.add_task(backup_worker, indices, BACKUP_DIR)
    
    return {
        "status": "started",
        "total_files": len(indices)
    }

@app.get("/api/backup/status")
async def get_backup_status():
    """Queries current backup background task state."""
    return backup_status

@app.post("/api/files/delete")
async def delete_files(payload: DeleteRequest):
    """
    Safely deletes specified files from camera.
    Includes token verification and descends indices to avoid PTP shift anomalies.
    """
    if not payload.confirm or payload.token != SECURE_DELETE_TOKEN:
        raise HTTPException(
            status_code=403,
            detail="Verification failed. Invalid token or confirmation missing."
        )
        
    if backup_status["active"]:
        return JSONResponse(status_code=409, content={"status": "busy", "message": "Backup is active. Cannot delete files."})
        
    # POKA-YOKE DETAIL:
    # We sort indices in descending order!
    # Deleting file 3 shifts files 4+ down. If we delete starting from highest indices (e.g. 5, then 3),
    # the shift does not affect the correctness of lower indices.
    sorted_indices = sorted(payload.indices, reverse=True)
    
    deleted = []
    failed = []
    
    async with camera_lock:
        for idx in sorted_indices:
            if not await is_camera_connected():
                raise CameraConnectionError("Camera disconnected mid-deletion.")
                
            stdout, stderr, code = await execute_gphoto_raw(["--delete-file", str(idx)])
            if code == 0 and "Error" not in stderr:
                deleted.append(idx)
                logger.info(f"Successfully deleted file index {idx} from camera")
            else:
                logger.error(f"Failed to delete file index {idx}: {stderr.strip()}")
                failed.append({"index": idx, "reason": stderr.strip()})
                
    return {
        "status": "success" if not failed else "partial_success",
        "deleted_count": len(deleted),
        "deleted_indices": deleted,
        "failed": failed
    }

# ==============================================================================
# ADDITIONAL ENDPOINTS (THUMBNAILS, BACKUPS & SYSTEM STATUS)
# ==============================================================================

SVG_IMAGE = b'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160"><rect width="100%" height="100%" fill="#171f33"/><text x="50%" y="50%" fill="#bbcabf" font-family="sans-serif" font-size="14" text-anchor="middle" dominant-baseline="middle">PHOTO</text></svg>'
SVG_VIDEO = b'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160"><rect width="100%" height="100%" fill="#171f33"/><text x="50%" y="50%" fill="#bbcabf" font-family="sans-serif" font-size="14" text-anchor="middle" dominant-baseline="middle">VIDEO</text></svg>'

def get_readable_size(size_in_bytes: int) -> str:
    val = float(size_in_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if val < 1024.0:
            return f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{val:.1f} TB"

@app.get("/api/files/{index}/thumbnail")
async def get_thumbnail(index: int):
    """Fetches a preview thumbnail directly from cache or camera, returning fallback SVG on error."""
    global active_files_catalog
    
    # Resolve file name/size from cache catalog
    file_info = active_files_catalog.get(index)
    if not file_info:
        # Fallback to populating the catalog cache
        try:
            stdout = await execute_gphoto_safe(["--list-files"])
            files = parse_gphoto_file_list(stdout)
            active_files_catalog = {f["index"]: f for f in files}
            file_info = active_files_catalog.get(index)
        except Exception:
            pass
            
    if file_info:
        # 1. Cache-first check
        cache_filename = f"{file_info['name']}_{file_info['size'].replace(' ', '_')}.jpg"
        cache_path = os.path.join(CACHE_THUMB_DIR, cache_filename)
        
        if os.path.exists(cache_path):
            return FileResponse(cache_path, media_type="image/jpeg")
            
        # 2. Cache miss: Fetch from camera and store to cache
        if await is_camera_connected():
            async with camera_lock:
                try:
                    data = await fetch_preview_bytes(file_info["folder"], file_info["name"])
                    if len(data) > 0:
                        with open(cache_path, "wb") as thumb_f:
                            thumb_f.write(data)
                        return Response(content=data, media_type="image/jpeg")
                except Exception as ex:
                    logger.error(f"Failed to fetch thumbnail for index {index}: {ex}")
                    
    # Return fallback SVG
    return StreamingResponse(io.BytesIO(SVG_IMAGE), media_type="image/svg+xml")

@app.get("/api/backups")
async def list_backups():
    """Lists files successfully backed up in local persistent storage."""
    files = []
    if os.path.exists(BACKUP_DIR):
        for name in os.listdir(BACKUP_DIR):
            filepath = os.path.join(BACKUP_DIR, name)
            if os.path.isfile(filepath):
                stat = os.stat(filepath)
                mime, _ = mimetypes.guess_type(filepath)
                files.append({
                    "name": name,
                    "size": get_readable_size(stat.st_size),
                    "mime": mime or "application/octet-stream",
                    "date": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })
    return {
        "status": "success",
        "count": len(files),
        "files": files
    }

@app.get("/api/backups/{filename}/stream")
async def stream_backup(filename: str):
    """Streams a backed-up file with full HTTP range support for high-res seeking."""
    filepath = os.path.realpath(os.path.join(BACKUP_DIR, filename))
    if not filepath.startswith(os.path.realpath(BACKUP_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
        
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
        
    mime, _ = mimetypes.guess_type(filepath)
    return FileResponse(filepath, media_type=mime or "application/octet-stream")

@app.get("/api/system/status")
async def get_system_status():
    """Gathers real-time performance diagnostics and disk status from host proc files."""
    # Disk status
    try:
        total, used, free = shutil.disk_usage(BACKUP_DIR)
        pct_used = (used / total) * 100
        disk_data = {
            "total": get_readable_size(total),
            "used": get_readable_size(used),
            "free": get_readable_size(free),
            "pct": round(pct_used, 1)
        }
    except Exception as e:
        disk_data = {"total": "0 B", "used": "0 B", "free": "0 B", "pct": 0, "error": str(e)}

    # Memory status
    mem_total, mem_available = 0, 0
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1]) * 1024
        mem_used = mem_total - mem_available
        mem_pct = (mem_used / mem_total) * 100 if mem_total > 0 else 0
        mem_data = {
            "total": get_readable_size(mem_total),
            "used": get_readable_size(mem_used),
            "free": get_readable_size(mem_available),
            "pct": round(mem_pct, 1)
        }
    except Exception as e:
        mem_data = {"total": "0 B", "used": "0 B", "free": "0 B", "pct": 0, "error": str(e)}

    # CPU load average (1m)
    try:
        with open("/proc/loadavg", "r") as f:
            cpu_load = f.read().split()[0]
    except Exception:
        cpu_load = "0.00"

    # Uptime diagnostics
    try:
        with open("/proc/uptime", "r") as f:
            uptime_secs = float(f.read().split()[0])
            days = int(uptime_secs // 86400)
            hours = int((uptime_secs % 86400) // 3600)
            mins = int((uptime_secs % 3600) // 60)
            uptime_str = f"{days}d {hours}h {mins}m"
    except Exception:
        uptime_str = "Unknown"

    return {
        "status": "success",
        "cpu_load": cpu_load,
        "disk": disk_data,
        "memory": mem_data,
        "uptime": uptime_str,
        "version": "v1.0.0-stable",
        "camera_connected": await is_camera_connected()
    }

