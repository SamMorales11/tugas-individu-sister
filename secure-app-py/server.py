# server.py
import asyncio
import logging
import ssl
from typing import Dict, Any, Optional
from aiohttp import web, ClientSession, TCPConnector, ClientTimeout
import json

# --- Definisi Logger ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- 1. Konfigurasi Audit Logging ---
audit_logger = logging.getLogger('AuditLogger')
audit_logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - [AUDIT] - %(message)s'))
audit_logger.addHandler(handler)
audit_logger.propagate = False

# --- 2. Konfigurasi RBAC ---
ROLES = {
    "token-admin-123": "admin", # Bisa read & write
    "token-user-ABC": "user"    # Hanya bisa read
}
ENDPOINT_PERMISSIONS = {
    "/get": "user",
    "/set": "admin",
    "/replicate": "admin"
}

@web.middleware
async def rbac_middleware(request: web.Request, handler):
    """Middleware untuk RBAC berdasarkan token."""
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

    required_role = ENDPOINT_PERMISSIONS.get(request.path)
    if not required_role:
        return await handler(request)

    user_role = ROLES.get(token)

    if not user_role:
        audit_logger.warning(f"Akses DITOLAK (Token tidak valid) ke {request.path} dari {request.remote}")
        return web.json_response({"error": "Authorization token required or invalid"}, status=401)

    if user_role == "admin":
        audit_logger.info(f"Akses ADMIN '{token}' diizinkan ke {request.path} dari {request.remote}")
        return await handler(request)
    
    if user_role == required_role:
        audit_logger.info(f"Akses USER '{token}' diizinkan ke {request.path} dari {request.remote}")
        return await handler(request)

    audit_logger.warning(f"Akses DITOLAK (Role '{user_role}' tidak cukup) ke {request.path} dari {request.remote}")
    return web.json_response({"error": "Insufficient permissions"}, status=403)

# --- 3. Aplikasi Server Utama ---
class ServerApp:
    def __init__(self, node_id: str, replica_addr: Optional[str]):
        self.node_id = node_id
        self.replica_addr = replica_addr
        self.data: Dict[str, Any] = {}
        self.lock = asyncio.Lock()
        
        # --- REVISI DI SINI ---
        # Inisialisasi aplikasi aiohttp di dalam __init__
        self.app = web.Application(middlewares=[rbac_middleware])
        # ---------------------
        
        self.http_client: Optional[ClientSession] = None
        self.ssl_context_client = ssl.create_default_context()
        self.ssl_context_client.check_hostname = False
        self.ssl_context_client.verify_mode = ssl.CERT_NONE

    async def start_client(self):
        """Inisialisasi HTTP client untuk komunikasi antar node."""
        connector = TCPConnector(ssl=self.ssl_context_client)
        self.http_client = ClientSession(connector=connector, timeout=ClientTimeout(total=5))
        logger.info(f"Node {self.node_id}: HTTP client (HTTPS) siap.")

    async def close_client(self):
        """Menutup HTTP client."""
        if self.http_client:
            await self.http_client.close()
            logger.info(f"Node {self.node_id}: HTTP client ditutup.")

    # --- API Handlers ---
    async def handle_get(self, request: web.Request):
        key = request.query.get("key")
        if not key:
            return web.json_response({"error": "'key' query parameter required"}, status=400)
        
        async with self.lock:
            value = self.data.get(key)
        
        if value is None:
            audit_logger.info(f"GET key '{key}' tidak ditemukan (Not Found)")
            return web.json_response({"error": f"Key '{key}' not found"}, status=404)
        else:
            audit_logger.info(f"GET key '{key}' berhasil")
            return web.json_response({"key": key, "value": value})

    async def handle_set(self, request: web.Request):
        try:
            data = await request.json()
            key = data.get("key")
            value = data.get("value")
            if not key or value is None:
                return web.json_response({"error": "Missing 'key' or 'value'"}, status=400)

            async with self.lock:
                self.data[key] = value
            
            audit_logger.warning(f"SET key '{key}' = '{value}' berhasil di node {self.node_id}")

            # Replikasi ke node lain (jika ada)
            if self.replica_addr:
                asyncio.create_task(self._send_replication(key, value))

            return web.json_response({"status": "ok", "key": key, "value": value}, status=201)

        except json.JSONDecodeError:
             return web.json_response({"error": "Invalid JSON body"}, status=400)
        except Exception as e:
            logger.error(f"Error in handle_set: {e}", exc_info=True)
            return web.json_response({"error": "Internal server error"}, status=500)

    # --- Endpoint Internal ---
    async def _send_replication(self, key: str, value: Any):
        """Mengirim replikasi ke node lain (via HTTPS)."""
        if not self.replica_addr or not self.http_client:
            return

        url = f"{self.replica_addr}/replicate"
        payload = {"key": key, "value": value}
        try:
            headers = {"Authorization": "Bearer token-admin-123"}
            async with self.http_client.post(url, json=payload, headers=headers, timeout=2) as resp:
                if resp.status == 200:
                    audit_logger.info(f"Node {self.node_id}: Replikasi key '{key}' ke {self.replica_addr} berhasil.")
                else:
                    audit_logger.error(f"Node {self.node_id}: Replikasi key '{key}' ke {self.replica_addr} GAGAL. Status: {resp.status}")
        except Exception as e:
            audit_logger.error(f"Node {self.node_id}: Error replikasi key '{key}' ke {self.replica_addr}: {e}")

    async def handle_replicate(self, request: web.Request):
        """Menerima replikasi dari node primary."""
        try:
            data = await request.json()
            key = data.get("key")
            value = data.get("value")
            
            async with self.lock:
                self.data[key] = value
                
            audit_logger.info(f"Node {self.node_id}: (REPLIKA) Menerima update key '{key}' = '{value}'")
            return web.json_response({"status": "replicated"})
        
        except json.JSONDecodeError:
             return web.json_response({"error": "Invalid JSON body"}, status=400)
        except Exception as e:
            logger.error(f"Error in handle_replicate: {e}", exc_info=True)
            return web.json_response({"error": "Internal server error"}, status=500)

    async def start(self, host: str, port: int, ssl_context: ssl.SSLContext):
        """Menjalankan server aiohttp dengan RBAC middleware."""
        await self.start_client()
        
        self.app.add_routes([
            web.get('/get', self.handle_get),
            web.post('/set', self.handle_set),
            web.post('/replicate', self.handle_replicate),
        ])
        
        # --- REVISI: Pindahkan middleware ke __init__ ---
        # self.app.middlewares.append(rbac_middleware) # Baris ini sudah dipindahkan ke __init__

        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port, ssl_context=ssl_context)
        logger.info(f"Server {self.node_id} (HTTPS) berjalan di https://{host}:{port}")
        await site.start()
        
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()
            await self.close_client()