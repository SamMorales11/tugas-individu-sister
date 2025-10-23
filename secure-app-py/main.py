# main.py
import argparse
import asyncio
import logging
import ssl

from server import ServerApp

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    parser = argparse.ArgumentParser(description="Run a Secure K/V Store node.")
    parser.add_argument("--id", required=True, help="Unique ID (nodeA, nodeB)")
    parser.add_argument("--addr", required=True, help="Address for this node (e.g., 127.0.0.1:8000)")
    parser.add_argument("--replica", help="[Opsional] Alamat HTTPS node replika (e.g., https://127.0.0.1:8001)")
    parser.add_argument("--key", default="server.key", help="Path ke file server.key (SSL key)")
    parser.add_argument("--cert", default="server.crt", help="Path ke file server.crt (SSL cert)")

    args = parser.parse_args()

    host, port_str = args.addr.split(':')
    port = int(port_str)

    # --- 4. Konfigurasi SSL/TLS ---
    # (Requirement: Certificate management & Encryption)
    try:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(certfile=args.cert, keyfile=args.key)
        logger.info(f"Berhasil memuat SSL certificate dari {args.cert} dan key dari {args.key}")
    except FileNotFoundError:
        logger.error(f"FATAL: File key/sertifikat tidak ditemukan. Pastikan '{args.key}' dan '{args.cert}' ada.")
        logger.error("Jalankan: openssl req -x509 -newkey rsa:4096 -nodes -keyout server.key -out server.crt -days 365")
        return
    except Exception as e:
        logger.error(f"FATAL: Gagal memuat SSL context: {e}")
        return

    # Inisialisasi Aplikasi Server
    app = ServerApp(node_id=args.id, replica_addr=args.replica)

    # Jalankan server
    try:
        await app.start(host, port, ssl_context)
    except asyncio.CancelledError:
        logger.info(f"Node {args.id} dihentikan.")
    except Exception as e:
         logger.error(f"Node {args.id} crash: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Node dihentikan manual.")