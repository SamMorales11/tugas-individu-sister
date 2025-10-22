# consistent_hash.py
import hashlib
import bisect # Untuk pencarian efisien di list terurut
from typing import List, Dict

class ConsistentHashRing:
    """Implementasi consistent hashing ring sederhana."""
    def __init__(self, nodes: List[str] = None, replicas: int = 3):
        self.replicas = replicas
        self.ring: Dict[int, str] = {}  # hash -> node address
        self.sorted_keys: List[int] = [] # List hash terurut
        if nodes:
            for node in nodes:
                self.add_node(node)

    def _hash(self, key: str) -> int:
        """Menghasilkan hash integer untuk sebuah string."""
        # Gunakan sha1 dan ambil bagian depannya sbg integer
        h = hashlib.sha1(key.encode('utf-8')).digest()
        # Ambil 4 byte pertama (32 bit) dan konversi ke integer
        return int.from_bytes(h[:4], byteorder='big')

    def add_node(self, node: str):
        """Menambahkan node ke ring."""
        for i in range(self.replicas):
            # Buat 'virtual node' dengan menambahkan suffix
            key = f"{node}-{i}"
            h = self._hash(key)
            self.ring[h] = node
            bisect.insort(self.sorted_keys, h) # Masukkan sambil menjaga urutan
        # print(f"Added node {node}, ring size: {len(self.sorted_keys)}") # Debug

    def remove_node(self, node: str):
        """Menghapus node dari ring."""
        keys_to_remove = []
        hashes_to_remove = set()
        for i in range(self.replicas):
            key = f"{node}-{i}"
            h = self._hash(key)
            if h in self.ring:
                 del self.ring[h]
                 hashes_to_remove.add(h)

        self.sorted_keys = [k for k in self.sorted_keys if k not in hashes_to_remove]
        # print(f"Removed node {node}, ring size: {len(self.sorted_keys)}") # Debug


    def get_node(self, key: str) -> str:
        """Mendapatkan node yang bertanggung jawab untuk sebuah key."""
        if not self.ring:
            return None

        h = self._hash(key)
        # Cari posisi hash key di list terurut
        idx = bisect.bisect_left(self.sorted_keys, h)

        # Jika index di akhir, wrap around ke node pertama
        if idx == len(self.sorted_keys):
            idx = 0

        # Kembalikan alamat node yang berasosiasi dengan hash tersebut
        return self.ring[self.sorted_keys[idx]]

    def get_nodes(self, key: str, count: int) -> List[str]:
        """Mendapatkan 'count' node unik yang bertanggung jawab (untuk replikasi)."""
        if not self.ring:
            return []
        if count > len(set(self.ring.values())): # Pastikan count tidak > jumlah node unik
             count = len(set(self.ring.values()))


        h = self._hash(key)
        idx = bisect.bisect_left(self.sorted_keys, h)
        if idx == len(self.sorted_keys):
            idx = 0

        nodes = []
        seen_nodes = set()
        start_idx = idx
        while len(nodes) < count and len(seen_nodes) < len(set(self.ring.values())):
            node_addr = self.ring[self.sorted_keys[idx]]
            if node_addr not in seen_nodes:
                nodes.append(node_addr)
                seen_nodes.add(node_addr)

            idx = (idx + 1) % len(self.sorted_keys)
            if idx == start_idx and len(nodes)<count: # Jika sudah kembali ke awal tapi belum cukup
                break # Hindari infinite loop jika node < count

        return nodes