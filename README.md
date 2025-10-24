# Tugas Individu - Implementasi Sistem Terdistribusi

Repositori ini berisi implementasi tiga sistem terdistribusi fundamental sebagai bagian dari tugas individu mata kuliah Sistem Paralel dan Terdistribusi. Setiap sistem diimplementasikan dalam Python menggunakan `asyncio` dan `aiohttp`.

## 📚 Ringkasan Proyek

Tugas ini terdiri dari tiga bagian utama dan satu bagian bonus:

1.  **Distributed Lock Manager (Raft):** Implementasi manajer kunci terdistribusi yang menggunakan algoritma konsensus Raft (versi disederhanakan) untuk memastikan hanya satu atau beberapa klien yang dapat mengakses sumber daya kritis pada satu waktu, dengan dukungan *shared* dan *exclusive lock* serta deteksi *deadlock*.
2.  **Distributed Queue System (Consistent Hashing):** Implementasi sistem antrean pesan terdistribusi yang menggunakan *consistent hashing* untuk partisi data. Sistem ini mendukung *multiple producers/consumers*, *message persistence* ke disk, *recovery* saat startup, replikasi data sederhana, dan jaminan pengiriman *at-least-once* melalui mekanisme ACK.
3.  **Distributed Cache Coherence (MESI):** Implementasi sistem cache terdistribusi yang menjaga konsistensi data antar node menggunakan protokol MESI. Sistem ini mendukung *multiple cache nodes*, menangani *cache invalidation* saat terjadi penulisan, menggunakan kebijakan penggantian LRU (Least Recently Used), dan menyediakan *performance monitoring*.
4.  **(Bonus) Secure App (Security & Encryption):** Implementasi *key-value store* 2-node yang aman, menerapkan *Audit Logging*, RBAC (*Role-Based Access Control*), dan enkripsi komunikasi *end-to-end* antar node dan klien menggunakan HTTPS (TLS/SSL).

## 🛠️ Stack Teknologi

* **Python:** Versi 3.8+
* **Asyncio:** Untuk pemrograman asinkron.
* **Aiohttp:** Untuk membangun server HTTP asinkron (API & komunikasi internal).
* **Aiofiles:** Untuk operasi file asinkron (digunakan di Queue System).

## 📁 Struktur Proyek

Repositori ini diorganisir ke dalam folder terpisah untuk setiap bagian tugas:

* `distributed-lock-py/`: Berisi implementasi Distributed Lock Manager.
* `queue-py/`: Berisi implementasi Distributed Queue System.
* `cache-py/`: Berisi implementasi Distributed Cache Coherence.
* `secure-app-py/`: Berisi implementasi Proyek Bonus Pilihan D.

Setiap folder proyek berisi kode sumber (`.py`) dan file `requirements.txt` untuk dependensinya.

---

## 🚀 Menjalankan dan Menguji

### **A. Distributed Lock Manager (Raft)**

#### Deskripsi Singkat
Manajer kunci terdistribusi berbasis Raft untuk koordinasi akses sumber daya.

#### Cara Menjalankan
1.  Navigasi ke direktori `distributed-lock-py/src`.
2.  Instal dependensi: `pip install -r ../requirements.txt` (jika belum).
3.  Jalankan 3 node di **tiga terminal terpisah**:
    ```powershell
    # Terminal 1 (Node 1)
    python main.py --id="node1" --raft_addr="127.0.0.1:7000" --http_addr="127.0.0.1:8000" --peers="127.0.0.1:7000,127.0.0.1:7001,127.0.0.1:7002" --peer_http_addrs="127.0.0.1:8000,127.0.0.1:8001,127.0.0.1:8002"

    # Terminal 2 (Node 2)
    python main.py --id="node2" --raft_addr="127.0.0.1:7001" --http_addr="127.0.0.1:8001" --peers="127.0.0.1:7000,127.0.0.1:7001,127.0.0.1:7002" --peer_http_addrs="127.0.0.1:8000,127.0.0.1:8001,127.0.0.1:8002"

    # Terminal 3 (Node 3)
    python main.py --id="node3" --raft_addr="127.0.0.1:7002" --http_addr="127.0.0.1:8002" --peers="127.0.0.1:7000,127.0.0.1:7001,127.0.0.1:7002" --peer_http_addrs="127.0.0.1:8000,127.0.0.1:8001,127.0.0.1:8002"
    ```
4.  Tunggu beberapa saat hingga leader terpilih (terlihat dari log `WON election` dan `starting heartbeats`).

#### Cara Menguji (Contoh di PowerShell)
1.  **Cari Leader:** Gunakan endpoint `/status` di setiap node API (port 8000, 8001, 8002) untuk menemukan node dengan `"state": "LEADER"`.
    ```powershell
    Invoke-WebRequest -Uri [http://127.0.0.1:8001/status](http://127.0.0.1:8001/status) | ConvertFrom-Json
    ```
2.  **Kirim Perintah ke Leader:** (Ganti `<LEADER_HTTP_ADDR>` dengan alamat leader, misal `http://127.0.0.1:8001`)
    ```powershell
    # Acquire Exclusive Lock
    $bodyAcquire = '{"lock_name": "kunci-raft", "lock_type": "exclusive", "client_id": "klien-A"}'
    Invoke-WebRequest -Uri <LEADER_HTTP_ADDR>/acquire -Method POST -ContentType "application/json" -Body $bodyAcquire

    # Release Lock
    $bodyRelease = '{"lock_name": "kunci-raft", "client_id": "klien-A"}'
    Invoke-WebRequest -Uri <LEADER_HTTP_ADDR>/release -Method POST -ContentType "application/json" -Body $bodyRelease
    ```

### **B. Distributed Queue System (Consistent Hashing)**

#### Deskripsi Singkat
Sistem antrean pesan terdistribusi yang *fault-tolerant* dengan *persistence* dan replikasi.

#### Cara Menjalankan
1.  Navigasi ke direktori `queue-py/`.
2.  Instal dependensi: `pip install -r requirements.txt` (jika belum).
3.  Jalankan 3 node di **tiga terminal terpisah**:
    ```powershell
    # Terminal 1 (Node A)
    python main.py --id="nodeA" --addr="127.0.0.1:8000" --peers="127.0.0.1:8000,127.0.0.1:8001,127.0.0.1:8002" --dataDir="data/nodeA"

    # Terminal 2 (Node B)
    python main.py --id="nodeB" --addr="127.0.0.1:8001" --peers="127.0.0.1:8000,127.0.0.1:8001,127.0.0.1:8002" --dataDir="data/nodeB"

    # Terminal 3 (Node C)
    python main.py --id="nodeC" --addr="127.0.0.1:8002" --peers="127.0.0.1:8000,127.0.0.1:8001,127.0.0.1:8002" --dataDir="data/nodeC"
    ```
4.  Folder `data/` akan dibuat untuk menyimpan log pesan.

#### Cara Menguji (Contoh di PowerShell)
1.  **Produce Pesan:** (Kirim ke node mana saja, server akan *forward* jika perlu)
    ```powershell
    $pesan = '{"queue": "nama-antrean", "body": "isi pesan baru"}'
    Invoke-WebRequest -Uri [http://127.0.0.1:8000/produce](http://127.0.0.1:8000/produce) -Method POST -ContentType "application/json" -Body $pesan
    ```
    *(Output diharapkan: `201 Created`)*
2.  **Consume Pesan:** (Kirim ke node yang benar berdasarkan *consistent hashing* - lihat log server saat *produce* atau coba saja)
    ```powershell
    # Ganti port jika perlu (misal, ke 8001)
    $pesanDiterima = Invoke-WebRequest -Uri "[http://127.0.0.1:8001/consume?queue=nama-antrean](http://127.0.0.1:8001/consume?queue=nama-antrean)" | ConvertFrom-Json
    $pesanDiterima # Catat ID pesan
    ```
3.  **Acknowledge Pesan:** (Kirim ke node yang sama tempat *consume*)
    ```powershell
    $messageId = $pesanDiterima.id
    $ackBody = '{"message_id": "' + $messageId + '"}'
    # Ganti port jika perlu (misal, ke 8001)
    Invoke-WebRequest -Uri [http://127.0.0.1:8001/ack](http://127.0.0.1:8001/ack) -Method POST -ContentType "application/json" -Body $ackBody
    ```
    *(Output diharapkan: `{"status": "acknowledged"}`)*

### **C. Distributed Cache Coherence (MESI)**

#### Deskripsi Singkat
Sistem cache terdistribusi yang menjaga konsistensi menggunakan protokol MESI dan LRU.

#### Cara Menjalankan
1.  Navigasi ke direktori `cache-py/`.
2.  Instal dependensi: `pip install -r requirements.txt` (jika belum).
3.  Jalankan 3 node di **tiga terminal terpisah**:
    ```powershell
    # Terminal 1 (Node A)
    python main.py --addr="127.0.0.1:8000" --peers="[http://127.0.0.1:8001](http://127.0.0.1:8001),[http://127.0.0.1:8002](http://127.0.0.1:8002)" --capacity=10 --id="nodeA"

    # Terminal 2 (Node B)
    python main.py --addr="127.0.0.1:8001" --peers="[http://127.0.0.1:8000](http://127.0.0.1:8000),[http://127.0.0.1:8002](http://127.0.0.1:8002)" --capacity=10 --id="nodeB"

    # Terminal 3 (Node C)
    python main.py --addr="127.0.0.1:8002" --peers="[http://127.0.0.1:8000](http://127.0.0.1:8000),[http://127.0.0.1:8001](http://127.0.0.1:8001)" --capacity=10 --id="nodeC"
    ```
    *(Parameter `--capacity` menentukan ukuran cache)*

#### Cara Menguji (Contoh di PowerShell)
1.  **Write Data ke Node A:**
    ```powershell
    $data1 = '{"key": "nama-kota", "value": "Balikpapan"}'
    Invoke-WebRequest -Uri [http://127.0.0.1:8000/write](http://127.0.0.1:8000/write) -Method POST -ContentType "application/json" -Body $data1
    ```
2.  **Read Data dari Node A (Hit):**
    ```powershell
    Invoke-WebRequest -Uri "[http://127.0.0.1:8000/read?key=nama-kota](http://127.0.0.1:8000/read?key=nama-kota)" | ConvertFrom-Json
    ```
3.  **Read Data dari Node B (Miss, lalu simpan):**
    ```powershell
    Invoke-WebRequest -Uri "[http://127.0.0.1:8001/read?key=nama-kota](http://127.0.0.1:8001/read?key=nama-kota)" | ConvertFrom-Json
    ```
    *(Akan mengambil dari simulasi memori)*
4.  **Update Data dari Node A (Memicu Invalidate):**
    ```powershell
    $dataUpdate = '{"key": "nama-kota", "value": "Samarinda"}'
    Invoke-WebRequest -Uri [http://127.0.0.1:8000/write](http://127.0.0.1:8000/write) -Method POST -ContentType "application/json" -Body $dataUpdate
    ```
    *(Periksa log Node B, akan ada pesan invalidasi)*
5.  **Cek Metrik:**
    ```powershell
    Invoke-WebRequest -Uri [http://127.0.0.1:8001/metrics](http://127.0.0.1:8001/metrics) | ConvertFrom-Json
    ```

### **D. (Bonus) Secure App (Security & Encryption)**

#### Deskripsi Singkat
Implementasi *key-value store* 2-node yang aman dengan HTTPS, RBAC, dan Audit Log.

#### Cara Menjalankan
1.  Navigasi ke direktori `secure-app-py/`.
2.  Instal dependensi: `pip install -r requirements.txt` (jika belum).
3.  **Buat Sertifikat SSL (Hanya sekali):** Jika belum ada `server.key` dan `server.crt`, buat menggunakan **Git Bash**:
    ```bash
    openssl req -x509 -newkey rsa:4096 -nodes -keyout server.key -out server.crt -days 365
    ```
    *(Tekan Enter untuk semua pertanyaan)*
4.  Jalankan 2 node di **dua terminal terpisah**:
    ```powershell
    # Terminal 1 (Node A - Primary)
    python main.py --id="nodeA" --addr="127.0.0.1:8000" --replica="[https://127.0.0.1:8001](https://127.0.0.1:8001)"

    # Terminal 2 (Node B - Replica)
    python main.py --id="nodeB" --addr="127.0.0.1:8001"
    ```

#### Cara Menguji (Contoh di PowerShell menggunakan `curl.exe`)
**Catatan:** Kita harus menggunakan `curl.exe -k` untuk mengabaikan *self-signed certificate*.

1.  **Uji Gagal (Tanpa Token):**
    ```powershell
    curl.exe -k "[https://127.0.0.1:8000/get?key=kunci1](https://127.0.0.1:8000/get?key=kunci1)"
    ```
    *(Output diharapkan: `{"error":"Authorization token required or invalid"}`)*

2.  **Uji Role "user" (Gagal Tulis):**
    ```powershell
    $dataUser = "{\"key\": \"kunci1\", \"value\": \"gagal\"}"
    curl.exe -k -X POST -H "Authorization: Bearer token-user-ABC" -H "Content-Type: application/json" -d $dataUser "[https://127.0.0.1:8000/set](https://127.0.0.1:8000/set)"
    ```
    *(Output diharapkan: `{"error":"Insufficient permissions"}`)*

3.  **Uji Role "admin" (Berhasil Tulis):**
    ```powershell
    $dataAdmin = "{\"key\": \"kunci1\", \"value\": \"berhasil\"}"
    curl.exe -k -X POST -H "Authorization: Bearer token-admin-123" -H "Content-Type: application/json" -d $dataAdmin "[https://127.0.0.1:8000/set](https://127.0.0.1:8000/set)"
    ```
    *(Output diharapkan: `{"status":"ok","key":"kunci1","value":"berhasil"}`)*

4.  **Verifikasi Replikasi (Baca dari Node B):**
    ```powershell
    curl.exe -k -H "Authorization: Bearer token-user-ABC" "[https://127.0.0.1:8001/get?key=kunci1](https://127.0.0.1:8001/get?key=kunci1)"
    ```
    *(Output diharapkan: `{"key":"kunci1","value":"berhasil"}`)*

---

## ⚠️ Catatan Penting & Troubleshooting

* **Firewall/Antivirus:** Masalah paling umum saat menjalankan di lokal adalah `connection refused` karena Firewall (Windows Defender atau Antivirus pihak ketiga) memblokir komunikasi antar node. Pastikan untuk **mengizinkan akses** saat pop-up firewall muncul, atau tambahkan **pengecualian (exception)** secara manual untuk Python atau port yang digunakan (700x, 800x).
* **HTTPS Error:** Saat menguji proyek *secure app* (Bonus D), pastikan menggunakan `https://` dan *flag* `-k` (untuk `curl.exe`) atau `-SkipCertificationCheck` (untuk `Invoke-WebRequest` jika didukung).
* **Alamat IP:** Semua contoh menggunakan `127.0.0.1`. Jika Anda menjalankan antar komputer berbeda, ganti dengan alamat IP yang sesuai.
* **Port:** Pastikan port yang digunakan tidak sedang dipakai oleh aplikasi lain.
* **Kesalahan Klien:** Perhatikan pesan error dari server (misalnya `Not the leader`, `Wrong node`, `Invalid JSON`). Kirim perintah ke node yang benar dan pastikan format JSON sudah valid.

---