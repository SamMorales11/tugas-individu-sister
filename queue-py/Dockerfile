# Dockerfile for Distributed Queue System (Python/Asyncio)

# 1. Pilih base image Python
FROM python:3.9-slim

# 2. Set working directory
WORKDIR /app

# 3. Salin requirements dan install dependensi (aiohttp, aiofiles)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 4. Salin semua file kode Python (.py)
COPY *.py ./

# 5. Ekspos port API (misal 8000-8002)
EXPOSE 8000-8002

# 6. Perintah default untuk menjalankan aplikasi
# Argumen --id, --addr, --peers, --dataDir akan diberikan saat runtime
CMD ["python", "main.py"]