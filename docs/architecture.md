# Arsitektur Sistem Sinkronisasi Terdistribusi

Dokumen ini menjelaskan arsitektur tingkat tinggi dari Sistem Sinkronisasi Terdistribusi, yang terdiri dari tiga komponen inti yang dirancang untuk bekerja secara konkuren dan fault-tolerant.

## 1. Arsitektur Umum

Sistem ini dirancang sebagai arsitektur *microservices* terdistribusi, di mana setiap *node* menjalankan tiga layanan inti. Sistem ini dikemas menggunakan **Docker** dan diorkestrasi oleh **Docker Compose**, memungkinkan skalabilitas dan isolasi yang mudah.

Komunikasi antar-node untuk konsensus (Raft) dan propagasi cache menggunakan komunikasi HTTP/RPC internal, sementara klien berinteraksi dengan *node* mana pun melalui API HTTP publik. **Redis** digunakan sebagai *state store* persisten eksternal untuk Distributed Queue, memastikan *durability* pesan.

![](diagram/high_level_architecture.png)
*(Diagram di atas harus mengilustrasikan 3+ node, satu Klien, dan satu instans Redis. Setiap node harus menunjukkan 3 komponen internal: Lock, Queue, Cache.)*

---

## 2. Komponen Sistem

### A. Distributed Lock Manager

Komponen ini bertanggung jawab untuk menyediakan mekanisme *locking* yang konsisten di seluruh cluster.

* **Algoritma:** Menggunakan **Raft Consensus Algorithm**.
* **Struktur:** Cluster terdiri dari minimal 3 *node* (memungkinkan 1 *node failure*). Setiap *node* dapat berada dalam status `Follower`, `Candidate`, atau `Leader`.
* **Konsistensi:** Semua permintaan *write* (acquire, release) diteruskan ke *Leader* dan direplikasi ke mayoritas *node* melalui *log replication* Raft sebelum dianggap *committed*. Ini menjamin *strong consistency*.
* **Fitur:**
    * **Shared (Read) & Exclusive (Write) Locks:** State machine dapat mengelola antrean permintaan, mengizinkan banyak *shared lock* atau satu *exclusive lock*.
    * **Deadlock Detection:** Menggunakan *wait-for graph* yang direplikasi. Jika permintaan *acquire* baru akan membuat siklus dalam *graph*, permintaan tersebut ditolak dengan *error deadlock*.
    * **Fault Tolerance:** Sistem tetap tersedia selama mayoritas *node* (misalnya, 2 dari 3) tetap hidup. Jika *Leader* gagal, pemilihan baru akan dipicu secara otomatis.

### B. Distributed Queue System

Komponen ini menyediakan layanan antrean pesan yang terdistribusi dan persisten.

* **Algoritma:** Menggunakan **Consistent Hashing** untuk memetakan *key* antrean (misalnya, `queue_name`) ke *node* yang bertanggung jawab atas partisi tersebut.
* **Struktur:** *Producer* dapat mengirim pesan ke *node* mana pun. *Node* tersebut akan menggunakan *hash ring* untuk meneruskan (me-redirect) permintaan ke *node* yang benar. *Consumer* mengambil pesan dari *node* yang bertanggung jawab.
* **Fitur:**
    * **Message Persistence:** Pesan yang di-*enqueue* disimpan di **Redis**. Ini memisahkan penyimpanan dari *node* itu sendiri, memungkinkan *node* gagal tanpa kehilangan data.
    * **At-Least-Once Delivery:** *Consumer* harus mengirimkan *acknowledgment* (ACK) setelah berhasil memproses pesan. Jika tidak ada ACK (misalnya, *consumer* crash), pesan akan tetap ada di antrean (atau dikembalikan ke antrean setelah *timeout*) untuk diproses ulang oleh *consumer* lain.
    * **Node Failure:** Jika sebuah *node* gagal, *hash ring* akan secara otomatis me-*rebalance* tanggung jawab partisi ke *node* lain yang masih hidup.

### C. Distributed Cache Coherence

Komponen ini mensimulasikan *cache coherence protocol* untuk menjaga konsistensi data di antara *cache* lokal pada setiap *node*.

* **Algoritma:** Menggunakan protokol **MESI** (Modified, Exclusive, Shared, Invalid).
* **Struktur:** Setiap *node* memiliki *cache* lokal (misalnya, *in-memory dictionary*). Semua *node* "menguping" (*snoop*) aktivitas di *bus* komunikasi (disimulasikan melalui *broadcast* RPC).
* **Fitur:**
    * **Cache Invalidation:** Ketika sebuah *node* ingin melakukan *write* (`POST /cache/{key}`) ke data yang statusnya `Shared`, ia harus terlebih dahulu menyiarkan pesan *invalidate* ke semua *node* lain. *Node* lain akan menandai *line cache* mereka sebagai `Invalid`.
    * **Update Propagation:** Setelah *write*, status *cache line* menjadi `Modified`. Jika *node* lain mencoba membaca (`GET /cache/{key}`) data tersebut, *node* yang memegang status `Modified` akan "menulis kembali" (*write-back*) data tersebut ke sumber utama (simulasi) dan mengubah statusnya menjadi `Shared` sehingga *node* lain dapat membacanya.
    * **Replacement Policy:** Menerapkan **LRU (Least Recently Used)** untuk mengeluarkan *entry* dari *cache* lokal ketika *cache* sudah penuh.

---

## 3. Tumpukan Teknologi (Tech Stack)

* **Bahasa:** Python 3.8+ (dengan `asyncio`, `aiohttp`)
* **State & Persistence:** Redis
* **Containerization:** Docker & Docker Compose
* **API:** HTTP REST (didefinisikan dalam `api_spec.yaml`)
* **Testing:** Pytest (Unit), Locust (Load Test)