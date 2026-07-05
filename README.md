# BasicCamera — PTP Camera Manager & Web Dashboard

[English](README.md) | [Türkçe](README.tr.md)

BasicCamera is a Dockerized FastAPI backend that manages a Nikon DSC Coolpix S2900 (`04b0:035e`) over USB/PTP. It lists, streams, backs up, and deletes photos and videos through a web dashboard — with zero idle resource usage via udev hotplug control.

---

## Key Features

- **Zero-idle resource** — udev rules start the Docker container on USB connect and stop it on disconnect
- **Async FastAPI backend** — Persistent gphoto2 session with auto-recovery on USB failures
- **Memory-efficient streaming** — Large media files streamed in 64 KB chunks without loading into RAM
- **Web dashboard** — Built-in HTML UI at `/` for gallery, preview, backup, and delete operations
- **Thumbnail cache** — Generated previews cached on disk for fast gallery loading
- **Poka-yoke safeguards:**
  - USB disconnect returns `{ "status": "camera_disconnected" }` instead of crashing
  - `asyncio.Lock` serializes PTP requests to prevent buffer overflow
  - Deletes processed in descending index order to prevent PTP index shift bugs
  - Delete requires `confirm=True` and `SECURE_DELETE_TOKEN` env var

---

## Architecture

| Component | Description |
|-----------|-------------|
| `app.py` | FastAPI server, gphoto2 wrapper, API endpoints |
| `index.html` | Web dashboard UI |
| `Dockerfile` | Multi-stage build with gphoto2 CLI + python-gphoto2 |
| `docker-compose.yml` | USB device mapping (`/dev/bus/usb`) |
| `99-nikon-camera.rules` | udev hotplug trigger |

**Language:** Python 3.11 · **Dependencies:** FastAPI, Uvicorn, gphoto2, Pillow

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Camera connection status |
| GET | `/api/files` | List files on camera |
| GET | `/api/files/{index}/preview` | Low-res preview |
| GET | `/api/files/{index}/stream` | Full-resolution stream |
| GET | `/api/files/{index}/thumbnail` | Cached thumbnail |
| POST | `/api/backup` | Backup all files to storage |
| GET | `/api/backup/status` | Backup progress |
| POST | `/api/files/delete` | Delete files (requires confirmation) |
| GET | `/api/backups` | List backed-up files |
| GET | `/api/system/status` | System and storage info |

---

## Setup

### 1. Install udev rule (host)

```bash
sudo cp 99-nikon-camera.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 2. Build and create container (first run)

```bash
docker compose build
docker compose up --no-start
```

The container uses `restart: "no"` — lifecycle is fully controlled by udev.

### 3. Connect camera

Plug in the Nikon Coolpix S2900 via USB. udev starts the container automatically. Open [http://localhost:8000](http://localhost:8000).

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECURE_DELETE_TOKEN` | *(required for delete)* | Secret token for delete operations — set in env, never commit |
| `REMOTE_CAMERA_HOST` | — | Optional: remote host for SSH camera access |
| `REMOTE_CAMERA_SSH_USER` | — | SSH user when using remote mode (e.g. `camera`) |
| `REMOTE_CAMERA_PYTHON` | `python3` | Python interpreter path on remote host |

---

## Troubleshooting

If the desktop environment locks the camera (`Could not claim the USB device`):

```bash
killall gvfsd-gphoto2
```

---

## License

MIT License
