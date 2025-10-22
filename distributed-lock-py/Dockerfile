# Dockerfile for Distributed Lock Manager (Python/Asyncio)

# 1. Pilih base image Python yang sesuai
FROM python:3.9-slim

# 2. Set working directory di dalam container
WORKDIR /app

# 3. Salin file requirements dan install dependensi
# Pisahkan agar layer ini di-cache jika requirements tidak berubah
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 4. Salin seluruh kode sumber proyek (folder src)
COPY src/ ./

# 5. Tentukan port yang akan diekspos (opsional, untuk dokumentasi)
# Port 700x untuk Raft, Port 800x untuk HTTP API
EXPOSE 7000-7002 8000-8002

# 6. Perintah default untuk menjalankan aplikasi saat container start
# Gunakan CMD agar bisa dioverride oleh docker-compose jika perlu
# Kita perlu menjalankan main.py dari dalam container
CMD ["python", "main.py"]

# Catatan: Argumen --id, --raft_addr, --http_addr, --peers akan
# diberikan saat menjalankan container (via docker run atau docker-compose)