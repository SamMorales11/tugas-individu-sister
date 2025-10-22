# main.py
import argparse
import asyncio
import logging
import string # Perlu import string
import random # Untuk ID jika tidak diberikan
from typing import List

from cache_node import CacheNode
from server import HTTPServer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Fungsi helper untuk generate ID acak jika tidak diberikan
def generate_random_id(length=8):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

async def main():
    parser = argparse.ArgumentParser(description="Run a Distributed Cache node.")
    parser.add_argument("--id", help="Unique ID for this node (default: random string)")
    parser.add_argument("--addr", required=True, help="Address for this node's HTTP API (e.g., 127.0.0.1:8000)")
    parser.add_argument("--peers", required=True, help="Comma-separated list of HTTP addresses of OTHER nodes (e.g., http://127.0.0.1:8001,http://127.0.0.1:8002)")
    parser.add_argument("--capacity", type=int, default=100, help="Cache capacity (number of items)")

    args = parser.parse_args()

    node_id = args.id if args.id else generate_random_id()
    http_host, http_port_str = args.addr.split(':')
    http_port = int(http_port_str)

    # Peers adalah daftar node LAIN
    peer_addrs = [p.strip() for p in args.peers.split(',') if p.strip()]

    # Inisialisasi Cache Node
    cache_node = CacheNode(node_id=node_id, capacity=args.capacity, peers=peer_addrs)

    # Inisialisasi HTTP Server
    http_server = HTTPServer(cache_node=cache_node)

    # Jalankan server
    server_task = asyncio.create_task(http_server.start(http_host, http_port), name=f"HTTPServer-{node_id}")

    logger.info(f"Node {node_id} running on {args.addr}. Capacity: {args.capacity}. Peers: {peer_addrs}")

    try:
        await server_task
    except asyncio.CancelledError:
        logger.info(f"Node {node_id} server task cancelled.")
    finally:
        await http_server.close_client() # Tutup http client saat shutdown
        logger.info(f"Node {node_id} shutting down.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Node stopped manually.")