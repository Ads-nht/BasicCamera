# ==========================================
# Builder Stage
# ==========================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Copy dependency definition
COPY requirements.txt .

# Install dependencies into a separate prefix path for isolation
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ==========================================
# Final Runner Stage
# ==========================================
FROM python:3.11-slim

WORKDIR /app

# Install runtime system packages (gphoto2 CLI and its supporting C library)
RUN apt-get update && apt-get install -y \
    gphoto2 \
    libgphoto2-6 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source code
COPY app.py .
COPY index.html .

# Create the persistent target directory for backups
RUN mkdir -p /storage/backup

# Expose FastAPI default port
EXPOSE 8000

# Run FastAPI app with Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
