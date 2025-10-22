# lock_manager.py
import asyncio
import logging
from typing import Dict, List, Set, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LockState:
    """Mewakili state dari sebuah kunci."""
    def __init__(self, name: str):
        self.name = name
        self.exclusive: bool = False
        self.holders: Set[str] = set() # Client IDs yang memegang kunci

class DistributedLockManager:
    """State machine yang mengelola semua kunci."""
    def __init__(self):
        self.locks: Dict[str, LockState] = {}
        # Antrean permintaan [lock_name] -> [(client_id, lock_type)]
        self.wait_queue: Dict[str, List[Tuple[str, str]]] = {}
        # Graf tunggu untuk deadlock [client_id] -> lock_name
        self.waits_for: Dict[str, str] = {}
        # Pemegang kunci [lock_name] -> [client_id] (untuk deadlock detection)
        self.lock_holder: Dict[str, List[str]] = {}
        self.lock = asyncio.Lock() # Untuk melindungi akses ke state

    async def apply_command(self, command: Dict) -> str:
        """Dipanggil oleh Raft setelah command di-commit."""
        async with self.lock:
            op = command.get("operation")
            lock_name = command.get("lock_name")
            client_id = command.get("client_id")
            lock_type = command.get("lock_type", "") # Default kosong untuk release

            logger.info(f"FSM Apply: op={op}, lock={lock_name}, client={client_id}")

            if op == "acquire":
                return self._handle_acquire(lock_name, client_id, lock_type)
            elif op == "release":
                return self._handle_release(lock_name, client_id)
            else:
                logger.error(f"Unrecognized command operation: {op}")
                return "error_unknown_operation"

    def _handle_acquire(self, lock_name: str, client_id: str, lock_type: str) -> str:
        """Logika internal untuk acquire, dipanggil di dalam lock."""
        lock = self.locks.get(lock_name)

        if not lock:
            # Kunci baru, langsung berikan
            new_lock = LockState(lock_name)
            new_lock.exclusive = (lock_type == "exclusive")
            new_lock.holders.add(client_id)
            self.locks[lock_name] = new_lock
            self.lock_holder[lock_name] = [client_id]
            logger.info(f"LockManager: Client '{client_id}' acquired NEW lock '{lock_name}' ({lock_type})")
            return "acquired"

        # Cek konflik
        can_acquire = False
        # Kondisi konflik: lock sedang exclusive ATAU kita minta exclusive & sudah ada yg pegang
        is_conflicting = lock.exclusive or (lock_type == "exclusive" and len(lock.holders) > 0)

        if not is_conflicting:
            # Hanya bisa acquire shared jika lock tidak exclusive DAN kita minta shared
             if not lock.exclusive and lock_type == "shared":
                 can_acquire = True
        # Atau bisa acquire (exclusive/shared) jika tidak ada holder sama sekali
        elif len(lock.holders) == 0:
            can_acquire = True


        if can_acquire:
            lock.holders.add(client_id)
            lock.exclusive = (lock_type == "exclusive") # Jadi exclusive jika kita minta exclusive
            if lock_name not in self.lock_holder:
                self.lock_holder[lock_name] = []
            self.lock_holder[lock_name].append(client_id)
            logger.info(f"LockManager: Client '{client_id}' acquired EXISTING lock '{lock_name}' ({lock_type})")
            return "acquired"
        else:
            # Harus menunggu
            logger.info(f"LockManager: Client '{client_id}' must WAIT for lock '{lock_name}'")
            if lock_name not in self.wait_queue:
                self.wait_queue[lock_name] = []
            self.wait_queue[lock_name].append((client_id, lock_type))
            self.waits_for[client_id] = lock_name

            # Deteksi deadlock
            if self._detect_deadlock(client_id, client_id):
                logger.warning(f"!!!!!!!! DEADLOCK DETECTED involving client '{client_id}' !!!!!!!!")
                # Hapus dari antrean tunggu untuk memutus deadlock
                del self.waits_for[client_id]
                self.wait_queue[lock_name].pop() # Hapus yang terakhir ditambah
                return "deadlock_detected"
            return "waiting"

    def _handle_release(self, lock_name: str, client_id: str) -> str:
        """Logika internal untuk release, dipanggil di dalam lock."""
        lock = self.locks.get(lock_name)
        if not lock:
            logger.warning(f"LockManager: Attempted to release non-existent lock '{lock_name}'")
            return "not_found"

        if client_id not in lock.holders:
            logger.warning(f"LockManager: Client '{client_id}' attempted to release lock '{lock_name}' it does not hold")
            return "not_holder"

        lock.holders.remove(client_id)

        # Update lock_holder map
        if lock_name in self.lock_holder:
             try:
                self.lock_holder[lock_name].remove(client_id)
                if not self.lock_holder[lock_name]: # Jika list jadi kosong
                    del self.lock_holder[lock_name]
             except ValueError:
                 pass # Client tidak ada di list holder (seharusnya tidak terjadi)


        logger.info(f"LockManager: Client '{client_id}' released lock '{lock_name}'")

        # Jika tidak ada lagi yg pegang, proses antrean & reset status exclusive
        if not lock.holders:
            lock.exclusive = False
            self._process_wait_queue(lock_name)

        return "released"

    def _process_wait_queue(self, lock_name: str):
        """Proses antrean jika ada yg menunggu lock yg baru dilepas."""
        if lock_name in self.wait_queue and self.wait_queue[lock_name]:
            client_id, lock_type = self.wait_queue[lock_name].pop(0) # Ambil yg pertama
            if not self.wait_queue[lock_name]: # Hapus key jika list kosong
                del self.wait_queue[lock_name]
            if client_id in self.waits_for:
                 del self.waits_for[client_id]

            logger.info(f"LockManager: Processing waiting client '{client_id}' for lock '{lock_name}'")
            # Coba berikan lock ke client yg menunggu (hasilnya diabaikan krn ini proses internal)
            self._handle_acquire(lock_name, client_id, lock_type)

    def _detect_deadlock(self, start_client: str, current_client: str) -> bool:
        """Deteksi siklus dalam waits-for graph."""
        waiting_for_lock = self.waits_for.get(current_client)
        if not waiting_for_lock:
            return False # Tidak menunggu, tidak ada siklus dari sini

        holders = self.lock_holder.get(waiting_for_lock)
        if not holders:
            return False # Kunci tidak dipegang siapa pun

        for holder_client in holders:
            if holder_client == start_client:
                return True # Siklus ditemukan!
            # Lanjut cari secara rekursif
            if self._detect_deadlock(start_client, holder_client):
                return True
        return False