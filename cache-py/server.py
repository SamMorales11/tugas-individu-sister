# server.py
import asyncio
import logging
from aiohttp import web, ClientSession, TCPConnector, ClientTimeout
import json

from cache_node import CacheNode # Import class CacheNode

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class HTTPServer:
    def __init__(self, cache_node: CacheNode):
        self.cache_node = cache_node
        self.app = web.Application()
        # Buat HTTP client untuk komunikasi antar node
        connector = TCPConnector(limit_per_host=20)
        self.http_client = ClientSession(connector=connector, timeout=ClientTimeout(total=5))
        # Berikan http_client ke cache_node
        self.cache_node.http_client = self.http_client
        self.setup_routes()

    async def close_client(self):
        """Menutup aiohttp ClientSession."""
        if self.http_client:
            await self.http_client.close()
            logger.info(f"Node {self.cache_node.node_id}: HTTP client session closed.")

    def setup_routes(self):
        self.app.router.add_get('/read', self.handle_read)
        self.app.router.add_post('/write', self.handle_write)
        self.app.router.add_post('/invalidate', self.handle_invalidate)
        self.app.router.add_get('/metrics', self.handle_metrics)

    async def handle_read(self, request: web.Request):
        key = request.query.get("key")
        if not key:
            return web.json_response({"error": "'key' query parameter is required"}, status=400)

        value, found = await self.cache_node.read(key)
        if not found:
            return web.json_response({"error": f"Key '{key}' not found"}, status=404)
        else:
            # Kembalikan sebagai JSON agar lebih fleksibel
            return web.json_response({"key": key, "value": value})

    async def handle_write(self, request: web.Request):
        try:
            data = await request.json()
            key = data.get("key")
            value = data.get("value")
            if not key or value is None: # Cek value juga
                return web.json_response({"error": "Missing 'key' or 'value' in JSON body"}, status=400)

            await self.cache_node.write(key, value)
            return web.json_response({"status": "accepted", "message": f"Write for key '{key}' accepted."}, status=202) # 202 Accepted

        except json.JSONDecodeError:
             return web.json_response({"error": "Invalid JSON body"}, status=400)
        except Exception as e:
            logger.error(f"Error in handle_write: {e}", exc_info=True)
            return web.json_response({"error": "Internal server error"}, status=500)

    async def handle_invalidate(self, request: web.Request):
        """Endpoint internal untuk menerima pesan invalidate."""
        try:
            data = await request.json()
            key = data.get("key")
            if not key:
                return web.json_response({"error": "Missing 'key' in JSON body"}, status=400)

            await self.cache_node.invalidate(key)
            return web.json_response({"status": "ok"}, status=200)

        except json.JSONDecodeError:
             return web.json_response({"error": "Invalid JSON body"}, status=400)
        except Exception as e:
            logger.error(f"Error in handle_invalidate: {e}", exc_info=True)
            return web.json_response({"error": "Internal server error"}, status=500)

    async def handle_metrics(self, request: web.Request):
        metrics = await self.cache_node.get_metrics()
        return web.json_response(metrics)

    async def start(self, host: str, port: int):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        logger.info(f"HTTP Server listening on http://{host}:{port}")
        await site.start()
        # Biarkan berjalan (akan dihandle di main.py)
        while True:
            await asyncio.sleep(3600)