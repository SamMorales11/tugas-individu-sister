# main.py
import argparse
import asyncio
import logging
import os # <-- IMPORT OS

from consistent_hash import ConsistentHashRing
from queue_node import QueueNode
from server import HTTPServer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    parser = argparse.ArgumentParser(description="Run a Distributed Queue node.")
    parser.add_argument("--id", required=True, help="Unique ID for this node (e.g., nodeA)")
    parser.add_argument("--addr", required=True, help="Address for this node's HTTP API (e.g., 127.0.0.1:8000)")
    parser.add_argument("--peers", required=True, help="Comma-separated list of addresses of ALL nodes in the cluster (including self)")
    parser.add_argument("--dataDir", required=True, help="Directory to store message logs (e.g., data/nodeA)") # <-- ARGUMEN BARU

    args = parser.parse_args()

    http_host, http_port_str = args.addr.split(':')
    http_port = int(http_port_str)

    all_node_addrs = args.peers.split(',')

    # Inisialisasi Consistent Hash Ring
    ring = ConsistentHashRing(nodes=all_node_addrs)

    # Inisialisasi Queue Node (Logic) dengan dataDir
    queue_node = QueueNode(node_id=args.id, data_dir=args.dataDir)
    await queue_node.initialize() # <-- PANGGIL INITIALIZE UNTUK RECOVERY

    # Inisialisasi HTTP Server (API)
    http_server = HTTPServer(node_id=args.id, self_addr=args.addr, ring=ring, queue_node=queue_node)

    # Jalankan server
    server_task = asyncio.create_task(http_server.start(http_host, http_port), name=f"HTTPServer-{args.id}")

    logger.info(f"Node {args.id} running on {args.addr}. Data dir: {args.dataDir}. Peers: {all_node_addrs}")

    try:
        await server_task
    except asyncio.CancelledError:
        logger.info(f"Node {args.id} server task cancelled.")
    finally:
        # --- TAMBAHAN: Cleanup ---
        await http_server.close_client() # Tutup http client
        await queue_node.close_files()   # Tutup file log
        logger.info(f"Node {args.id} shutting down.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Node stopped manually.")