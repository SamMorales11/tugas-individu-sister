# main.py
import argparse
import asyncio
import logging

from raft_node import RaftNode
from lock_manager import DistributedLockManager
from server import HTTPServer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    parser = argparse.ArgumentParser(description="Run a Raft node for Distributed Lock Manager.")
    parser.add_argument("--id", required=True, help="Unique ID for this node (e.g., node1)")
    parser.add_argument("--raft_addr", required=True, help="Address for Raft communication (e.g., 127.0.0.1:7000)")
    parser.add_argument("--http_addr", required=True, help="Address for HTTP API (e.g., 127.0.0.1:8000)")
    parser.add_argument("--peers", required=True, help="Comma-separated list of Raft addresses of ALL nodes (including self)")

    args = parser.parse_args()

    # Pisahkan host & port
    http_host, http_port_str = args.http_addr.split(':')
    http_port = int(http_port_str)

    # Daftar semua node (termasuk diri sendiri)
    all_nodes_raft_addr = args.peers.split(',')

    # Inisialisasi FSM (Lock Manager)
    lock_manager = DistributedLockManager()

    # Inisialisasi Node Raft
    raft_peers = [p for p in all_nodes_raft_addr if p != args.raft_addr]
    raft_node = RaftNode(node_id=args.raft_addr, peers=raft_peers, fsm=lock_manager)

    # Inisialisasi Server HTTP
    http_server = HTTPServer(raft_node)

    # ---- PERUBAHAN UTAMA DIMULAI DI SINI ----

    # Buat task untuk Raft node dan HTTP server
    raft_task = asyncio.create_task(raft_node.start(), name=f"RaftNode-{args.id}")
    server_task = asyncio.create_task(http_server.start(http_host, http_port), name=f"HTTPServer-{args.id}")

    logger.info(f"Node {args.id} tasks created. Running...")

    # Gunakan asyncio.gather untuk menjalankan kedua task secara bersamaan.
    # Program akan berjalan sampai salah satu task error atau dihentikan (misal Ctrl+C).
    try:
        await asyncio.gather(raft_task, server_task)
    except asyncio.CancelledError:
        logger.info(f"Node {args.id} tasks cancelled.")
    finally:
        # Pastikan semua task dibatalkan jika salah satu selesai/error
        if not raft_task.done():
            raft_task.cancel()
        if not server_task.done():
            server_task.cancel()
        logger.info(f"Node {args.id} shutting down.") # Pesan ini sekarang muncul saat benar-benar berhenti

    # ---- AKHIR PERUBAHAN ----


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Node stopped manually.")