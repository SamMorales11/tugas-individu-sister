# cache_node.py
import asyncio
import logging
from enum import Enum
from typing import Dict, Optional, Tuple, List, Any
import aiohttp # Pastikan aiohttp diimpor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MESIState(Enum):
    MODIFIED = 'M'
    EXCLUSIVE = 'E'
    SHARED = 'S'
    INVALID = 'I'

class CacheLine:
    """Satu baris data dalam cache, juga node untuk linked list LRU."""
    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value
        self.state: MESIState = MESIState.INVALID
        self.prev: Optional[CacheLine] = None
        self.next: Optional[CacheLine] = None

class CacheNode:
    """Implementasi cache node dengan MESI dan LRU."""
    def __init__(self, node_id: str, capacity: int, peers: List[str]):
        self.node_id = node_id
        self.capacity = capacity
        self.peers = peers
        self.lock = asyncio.Lock()
        self.lines: Dict[str, CacheLine] = {}
        self.head = CacheLine("HEAD", None)
        self.tail = CacheLine("TAIL", None)
        self.head.next = self.tail
        self.tail.prev = self.head
        self.main_memory: Dict[str, Any] = {} # Simulasi Main Memory Lokal
        self.hits = 0
        self.misses = 0
        self.invalidations_sent = 0
        self.invalidations_received = 0
        self.http_client: Optional[aiohttp.ClientSession] = None

    # --- Helper Methods for LRU ---
    def _remove_node(self, node: CacheLine):
        if node.prev: node.prev.next = node.next
        if node.next: node.next.prev = node.prev
        node.prev = node.next = None

    def _add_to_front(self, node: CacheLine):
        node.next = self.head.next
        node.prev = self.head
        if self.head.next: self.head.next.prev = node
        self.head.next = node

    def _move_to_front(self, node: CacheLine):
        self._remove_node(node)
        self._add_to_front(node)

    def _evict_lru(self):
        if self.tail.prev == self.head: return
        lru_node = self.tail.prev
        logger.info(f"Node {self.node_id}: Cache full (capacity {self.capacity}). Evicting LRU key '{lru_node.key}'")
        self._remove_node(lru_node)
        del self.lines[lru_node.key]
        # TODO: Write back jika Modified

    # --- Core Cache Operations ---
    async def read(self, key: str) -> Tuple[Optional[Any], bool]:
        """Membaca data dari cache (mengikuti logika MESI read)."""
        async with self.lock:
            line = self.lines.get(key)

            # === Cache Miss ===
            if not line or line.state == MESIState.INVALID:
                self.misses += 1
                logger.info(f"Node {self.node_id}: Cache MISS for key '{key}'")

                # ---- LOGIKA CACHE MISS DIPERBAIKI LAGI ----
                # 1. Ambil dari memori lokal (simulasi write-through)
                value = self.main_memory.get(key)
                if value is None:
                    # Jika tidak ada di memori lokal, berarti memang tidak pernah ditulis
                    # atau belum sampai ke node ini. Kembalikan not found.
                    logger.warning(f"Node {self.node_id}: Key '{key}' not found in local main memory simulation.")
                    return None, False # BENAR-BENAR TIDAK DITEMUKAN

                # 2. Jika ditemukan di memori lokal, masukkan/update cache
                if len(self.lines) >= self.capacity and (not line or line.state == MESIState.INVALID): # Evict hanya jika akan menambah line baru
                    self._evict_lru()

                # 3. Buat/Update cache line
                if not line: # Jika benar-benar baru
                    line = CacheLine(key, value)
                    self.lines[key] = line
                    self._add_to_front(line)
                else: # Jika state INVALID
                    line.value = value # Update value dari memori
                    self._move_to_front(line) # Pindahkan ke depan

                # 4. Tentukan state awal (Tetap Exclusive untuk sederhana)
                line.state = MESIState.EXCLUSIVE
                logger.info(f"Node {self.node_id}: Fetched key '{key}' from local memory sim. State set to {line.state.name}")
                return line.value, True
                # ---- AKHIR LOGIKA DIPERBAIKI ----

            # === Cache Hit ===
            else:
                self.hits += 1
                logger.info(f"Node {self.node_id}: Cache HIT for key '{key}' (State: {line.state.name})")
                self._move_to_front(line)
                return line.value, True

    async def write(self, key: str, value: Any):
        """Menulis data ke cache (mengikuti logika MESI write)."""
        async with self.lock:
            await self.broadcast_invalidate(key)
            line = self.lines.get(key)
            if not line or line.state == MESIState.INVALID:
                logger.info(f"Node {self.node_id}: Write MISS for key '{key}' (or was Invalid)")
                self.misses += 1
                if len(self.lines) >= self.capacity:
                    self._evict_lru()
                line = CacheLine(key, value)
                self.lines[key] = line
                self._add_to_front(line)
                line.state = MESIState.MODIFIED # Langsung Modified
            else:
                # Logika state transition saat Write Hit
                if line.state == MESIState.SHARED:
                    logger.info(f"Node {self.node_id}: Write HIT for SHARED key '{key}'. State changing to Modified.")
                elif line.state == MESIState.EXCLUSIVE:
                    logger.info(f"Node {self.node_id}: Write HIT for EXCLUSIVE key '{key}'. Changing state to Modified.")
                elif line.state == MESIState.MODIFIED:
                     logger.info(f"Node {self.node_id}: Write HIT for MODIFIED key '{key}'. State remains Modified.")
                line.value = value
                line.state = MESIState.MODIFIED
                self._move_to_front(line)

            # Simulasikan write-through ke main memory LOKAL
            self.main_memory[key] = value
            logger.info(f"Node {self.node_id}: Wrote key '{key}' = '{value}'. State is now {line.state.name}. Updated main memory.")

    async def invalidate(self, key: str):
        """Dipanggil oleh node lain untuk invalidate cache line lokal."""
        async with self.lock:
            line = self.lines.get(key)
            if line and line.state != MESIState.INVALID:
                self.invalidations_received += 1
                logger.info(f"Node {self.node_id}: Received invalidate for key '{key}'. Changing state from {line.state.name} to Invalid.")
                line.state = MESIState.INVALID

    async def broadcast_invalidate(self, key: str):
        """Mengirim pesan invalidate ke semua peer."""
        if not self.peers or not self.http_client or self.http_client.closed:
            logger.warning(f"Node {self.node_id}: Cannot broadcast invalidate; no peers or HTTP client not ready.")
            return
        self.invalidations_sent += len(self.peers)
        logger.info(f"Node {self.node_id}: Broadcasting invalidate for key '{key}' to {len(self.peers)} peers.")
        payload = {"key": key}
        tasks = []
        for peer_addr in self.peers:
            tasks.append(asyncio.create_task(self._send_invalidate_rpc(peer_addr, payload)))
        results = await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_invalidate_rpc(self, target_addr: str, payload: Dict):
         """Helper mengirim POST /invalidate."""
         url = f"{target_addr}/invalidate"
         try:
              async with self.http_client.post(url, json=payload, timeout=0.5) as resp:
                   if resp.status != 200:
                        logger.warning(f"Node {self.node_id}: Invalidate to {target_addr} returned status {resp.status}")
         except asyncio.TimeoutError:
              logger.warning(f"Node {self.node_id}: Timeout sending invalidate to {target_addr}")
         except Exception as e:
              if "Connect call failed" not in str(e): # Kurangi noise saat node lain belum siap
                    logger.error(f"Node {self.node_id}: Error sending invalidate to {target_addr}: {e}")

    async def get_metrics(self) -> Dict:
        """Mengembalikan metrik performa."""
        async with self.lock:
            total_accesses = self.hits + self.misses
            hit_rate = (float(self.hits) / total_accesses * 100) if total_accesses > 0 else 0
            return {
                "node_id": self.node_id,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate_percent": round(hit_rate, 2),
                "current_size": len(self.lines),
                "capacity": self.capacity,
                "invalidations_sent": self.invalidations_sent,
                "invalidations_received": self.invalidations_received,
            }