# main.py
import argparse
import asyncio
import logging
from typing import Dict

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
    # --- TAMBAHKAN ARGUMEN BARU UNTUK HTTP PEERS ---
    parser.add_argument("--peer_http_addrs", required=True, help="Comma-separated list of HTTP API addresses of ALL nodes (including self, in same order as --peers)")

    args = parser.parse_args()

    http_host, http_port_str = args.http_addr.split(':')
    http_port = int(http_port_str)

    all_nodes_raft_addr = args.peers.split(',')
    all_nodes_http_addr = args.peer_http_addrs.split(',') # <-- Ambil daftar alamat HTTP

    # --- BUAT PEMETAAN RAFT -> HTTP ---
    if len(all_nodes_raft_addr) != len(all_nodes_http_addr):
        raise ValueError("Number of raft addresses must match number of http addresses")
    peer_http_map: Dict[str, str] = dict(zip(all_nodes_raft_addr, all_nodes_http_addr))
    # ----------------------------------

    lock_manager = DistributedLockManager()

    # Peers untuk RaftNode adalah daftar alamat RAFT node LAIN
    raft_peers = [p for p in all_nodes_raft_addr if p != args.raft_addr]
    # Berikan pemetaan alamat ke RaftNode
    raft_node = RaftNode(node_id=args.raft_addr, peers=raft_peers, fsm=lock_manager, peer_http_map=peer_http_map)

    http_server = HTTPServer(raft_node)

    raft_task = asyncio.create_task(raft_node.start(), name=f"RaftNode-{args.id}")
    server_task = asyncio.create_task(http_server.start(http_host, http_port), name=f"HTTPServer-{args.id}")

    logger.info(f"Node {args.id} tasks created. Running...")

    try:
        await asyncio.gather(raft_task, server_task)
    except asyncio.CancelledError:
        logger.info(f"Node {args.id} tasks cancelled.")
    finally:
        if not raft_task.done(): raft_task.cancel()
        if not server_task.done(): server_task.cancel()
        logger.info(f"Node {args.id} shutting down.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Node stopped manually.")