import os
import re
import asyncio
import logging
import io
import shutil
import mimetypes
import datetime
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
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
BACKUP_DIR = "/storage/backup"
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
    
    Sample output format:
    There is no file in folder '/'.
    There is 1 file in folder '/store_00010001/DCIM'.
    There are 2 files in folder '/store_00010001/DCIM/100NIKON'.
    #1      DSCN0001.JPG               120 KB image/jpeg
    #2      DSCN0002.MOV              5120 KB video/quicktime
    """
    files = []
    current_folder = "/"
    folder_pattern = re.compile(r"in folder '([^']+)'")
    # Matches: #<index> <filename> <size> <mimetype>
    file_pattern = re.compile(r"^#(\d+)\s+(\S+)\s+(.+?)\s+([a-zA-Z0-9\-/]+)$")
    
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
            
        folder_match = folder_pattern.search(line)
        if folder_match:
            current_folder = folder_match.group(1)
            continue
            
        file_match = file_pattern.match(line)
        if file_match:
            index = int(file_match.group(1))
            name = file_match.group(2)
            size_str = file_match.group(3)
            mime = file_match.group(4)
            
            files.append({
                "index": index,
                "name": name,
                "folder": current_folder,
                "path": f"{current_folder}/{name}" if current_folder != "/" else f"/{name}",
                "size": size_str,
                "mime": mime
            })
            
    return files

# ==============================================================================
# SAFE EXECUTION CORE (POKA-YOKE FOR I/O CONFLICTS)
# ==============================================================================
async def execute_gphoto_raw(args: List[str]) -> tuple[str, str, int]:
    """Runs a raw gphoto2 command asynchronously."""
    try:
        process = await asyncio.create_subprocess_exec(
            "gphoto2", *args,
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
        logger.error(f"Failed to execute gphoto2 subprocess: {e}")
        return "", str(e), -1

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
async def list_files():
    """Lists all files on the digital camera."""
    if camera_lock.locked():
        return JSONResponse(status_code=409, content={"status": "busy", "message": "Camera is currently busy."})
        
    stdout = await execute_gphoto_safe(["--list-files"])
    files = parse_gphoto_file_list(stdout)
    return {
        "status": "success",
        "count": len(files),
        "files": files
    }

@app.get("/api/files/{index}/stream")
async def stream_file(index: int):
    """Streams a media asset directly from the camera without caching to server RAM."""
    if camera_lock.locked():
        return JSONResponse(status_code=409, content={"status": "busy", "message": "Camera is currently busy."})
        
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
        
    if camera_lock.locked():
        return JSONResponse(status_code=409, content={"status": "busy", "message": "Camera is currently busy."})
        
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
        
    if camera_lock.locked() or backup_status["active"]:
        return JSONResponse(status_code=409, content={"status": "busy", "message": "Camera is currently busy."})
        
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
    """Fetches a preview thumbnail directly from camera or returns a fallback SVG."""
    if not await is_camera_connected():
        return StreamingResponse(io.BytesIO(SVG_IMAGE), media_type="image/svg+xml")
        
    async with camera_lock:
        process = await asyncio.create_subprocess_exec(
            "gphoto2", "--get-thumbnail", str(index), "--stdout",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0 and len(stdout) > 0:
            return StreamingResponse(io.BytesIO(stdout), media_type="image/jpeg")
            
    # If thumbnail retrieval fails (e.g. for video files or connection glitch), return clean SVG
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

