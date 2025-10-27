Panduan Pengujian Distributed Lock Manager
Dokumen ini berisi langkah-langkah dan perintah yang diperlukan untuk menguji fungsionalitas penuh dari proyek Distributed Lock Manager Anda.

⚠️ Prasyarat Penting
Sebelum memulai tes 1-3, pastikan Anda telah mengatur variabel $LEADER_HTTP_ADDR di semua terminal PowerShell klien yang akan Anda gunakan.

Cari Leader Anda:

PowerShell

Invoke-WebRequest -Uri "http://127.0.0.1:8000/status" | ConvertFrom-Json
Invoke-WebRequest -Uri "http://127.0.0.1:8001/status" | ConvertFrom-Json
Invoke-WebRequest -Uri "http://127.0.0.1:8002/status" | ConvertFrom-Json
Atur Variabel Leader: (Ganti alamat di bawah ini dengan alamat Leader yang Anda temukan)

PowerShell

$LEADER_HTTP_ADDR = "http://127.0.0.1:8000"
Tes 1: Alur Dasar (Acquire & Release Exclusive Lock)
Tujuan: Memastikan fungsionalitas paling dasar (mendapatkan dan melepaskan satu exclusive lock) berfungsi.

A. Mendapatkan Kunci (Acquire)
PowerShell

# 1. Definisikan body
$bodyAcquire = '{"lock_name": "kunci-utama", "lock_type": "exclusive", "client_id": "tester-01"}'

# 2. Kirim permintaan
Invoke-WebRequest -Uri "$LEADER_HTTP_ADDR/acquire" -Method POST -ContentType "application/json" -Body $bodyAcquire
Output yang Diharapkan (Sukses HTTP 200): {"status":"acquired", "message":"Lock 'kunci-utama' acquired by 'tester-01'"}

B. Melepaskan Kunci (Release)
PowerShell

# 1. Definisikan body
$bodyRelease = '{"lock_name": "kunci-utama", "client_id": "tester-01"}'

# 2. Kirim permintaan
Invoke-WebRequest -Uri "$LEADER_HTTP_ADDR/release" -Method POST -ContentType "application/json" -Body $bodyRelease
Output yang Diharapkan (Sukses HTTP 200): {"status":"released", "message":"Lock 'kunci-utama' released by 'tester-01'"}

Tes 2: Pengujian Shared Lock (Banyak Pembaca)
Tujuan: Membuktikan bahwa dua klien berbeda dapat memegang shared lock pada kunci yang sama secara bersamaan.

A. Klien 01 Meminta Shared Lock (di Terminal 1)
PowerShell

$bodyShared1 = '{"lock_name": "kunci-shared", "lock_type": "shared", "client_id": "klien-01"}'
Invoke-WebRequest -Uri "$LEADER_HTTP_ADDR/acquire" -Method POST -ContentType "application/json" -Body $bodyShared1
Output yang Diharapkan (Sukses HTTP 200): {"status":"acquired", "message":"Lock 'kunci-shared' acquired by 'klien-01'"}

B. Klien 02 Meminta Shared Lock (di Terminal 2)
(Jalankan ini saat Klien 01 masih memegang kuncinya)

PowerShell

$bodyShared2 = '{"lock_name": "kunci-shared", "lock_type": "shared", "client_id": "klien-02"}'
Invoke-WebRequest -Uri "$LEADER_HTTP_ADDR/acquire" -Method POST -ContentType "application/json" -Body $bodyShared2
Output yang Diharapkan (Sukses HTTP 200): {"status":"acquired", "message":"Lock 'kunci-shared' acquired by 'klien-02'"}

Tes 3: Pengujian Deteksi Deadlock ☠️
Tujuan: Membuktikan server dapat mendeteksi siklus tunggu (A menunggu B, B menunggu A) dan membatalkannya.

A. Klien 01 mendapatkan 'lock-A' (di Terminal 1)
PowerShell

$bodyA1 = '{"lock_name": "lock-A", "lock_type": "exclusive", "client_id": "klien-01"}'
Invoke-WebRequest -Uri "$LEADER_HTTP_ADDR/acquire" -Method POST -ContentType "application/json" -Body $bodyA1
Output yang Diharapkan: Sukses (HTTP 200).

B. Klien 02 mendapatkan 'lock-B' (di Terminal 2)
PowerShell

$bodyB2 = '{"lock_name": "lock-B", "lock_type": "exclusive", "client_id": "klien-02"}'
Invoke-WebRequest -Uri "$LEADER_HTTP_ADDR/acquire" -Method POST -ContentType "application/json" -Body $bodyB2
Output yang Diharapkan: Sukses (HTTP 200).

C. Klien 01 menunggu 'lock-B' (Kembali ke Terminal 1)
PowerShell

$bodyB1 = '{"lock_name": "lock-B", "lock_type": "exclusive", "client_id": "klien-01"}'
Invoke-WebRequest -Uri "$LEADER_HTTP_ADDR/acquire" -Method POST -ContentType "application/json" -Body $bodyB1
Output yang Diharapkan (Menunggu HTTP 202): (Akan terlihat seperti error) Cari pesan JSON di output: {"status":"waiting", ...}

D. Klien 02 menunggu 'lock-A' (Kembali ke Terminal 2)
(Langkah ini memicu deteksi deadlock)

PowerShell

$bodyA2 = '{"lock_name": "lock-A", "lock_type": "exclusive", "client_id": "klien-02"}'
Invoke-WebRequest -Uri "$LEADER_HTTP_ADDR/acquire" -Method POST -ContentType "application/json" -Body $bodyA2
Output yang Diharapkan (Deadlock Terdeteksi HTTP 409): (Akan terlihat seperti error) Cari pesan JSON di output: {"status":"deadlock_detected", ...}