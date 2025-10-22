# server.py
import logging
import asyncio
from aiohttp import web

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class HTTPServer:
    def __init__(self, raft_node):
        self.raft_node = raft_node
        self.app = web.Application()
        self.setup_routes()

    def setup_routes(self):
        """Mendaftarkan semua endpoint HTTP."""
        self.app.router.add_post('/acquire', self.handle_acquire)
        self.app.router.add_post('/release', self.handle_release)
        self.app.router.add_get('/status', self.handle_status)
        # Endpoint internal Raft
        self.app.router.add_post('/request_vote', self.handle_request_vote)
        self.app.router.add_post('/append_entries', self.handle_append_entries)

    async def handle_acquire(self, request: web.Request):
        """Handler untuk /acquire dari klien."""
        try:
            data = await request.json()
            command = {
                "operation": "acquire",
                "lock_name": data.get("lock_name"),
                "lock_type": data.get("lock_type"),
                "client_id": data.get("client_id")
            }
            # Validasi input sederhana
            if not all([command["lock_name"], command["lock_type"], command["client_id"]]):
                 return web.json_response({"error": "Missing required fields"}, status=400)

            success, result_or_leader = await self.raft_node.client_request(command)

            if success:
                # Berhasil apply via Raft, kembalikan hasil FSM
                status = result_or_leader
                if status == "acquired":
                     return web.json_response({"status": "acquired", "message": f"Lock '{command['lock_name']}' acquired by '{command['client_id']}'"}, status=200)
                elif status == "waiting":
                     return web.json_response({"status": "waiting", "message": f"Request accepted, client '{command['client_id']}' is waiting"}, status=202) # 202 Accepted
                elif status == "deadlock_detected":
                     return web.json_response({"status": "deadlock_detected", "message": f"Deadlock detected for '{command['lock_name']}'"}, status=409) # 409 Conflict
                else:
                     return web.json_response({"status": "unknown", "message": f"Unknown FSM status: {status}"}, status=500)
            else:
                # Bukan leader atau gagal replikasi
                if result_or_leader == "replication_failed":
                     return web.json_response({"error": "Failed to replicate command to majority"}, status=503) # Service Unavailable
                else:
                    leader_id = result_or_leader if result_or_leader else "unknown"
                    return web.json_response({"error": "Not the leader", "leader_id": leader_id}, status=503) # Service Unavailable

        except Exception as e:
            logger.error(f"Error in handle_acquire: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)

    async def handle_release(self, request: web.Request):
        """Handler untuk /release dari klien."""
        try:
            data = await request.json()
            command = {
                "operation": "release",
                "lock_name": data.get("lock_name"),
                "client_id": data.get("client_id")
            }
            if not all([command["lock_name"], command["client_id"]]):
                 return web.json_response({"error": "Missing required fields"}, status=400)

            success, result_or_leader = await self.raft_node.client_request(command)

            if success:
                 status = result_or_leader
                 if status == "released":
                      return web.json_response({"status": "released", "message": f"Lock '{command['lock_name']}' released by '{command['client_id']}'"}, status=200)
                 elif status == "not_found":
                      return web.json_response({"status": "not_found", "message": f"Lock '{command['lock_name']}' not found"}, status=404)
                 elif status == "not_holder":
                      return web.json_response({"status": "not_holder", "message": f"Client '{command['client_id']}' does not hold lock"}, status=403) # Forbidden
                 else:
                      return web.json_response({"status": "unknown", "message": f"Unknown FSM status: {status}"}, status=500)
            else:
                 leader_id = result_or_leader if result_or_leader else "unknown"
                 return web.json_response({"error": "Not the leader", "leader_id": leader_id}, status=503)

        except Exception as e:
             logger.error(f"Error in handle_release: {e}")
             return web.json_response({"error": "Internal server error"}, status=500)


    async def handle_status(self, request: web.Request):
        """Handler untuk /status."""
        status = await self.raft_node.get_status()
        return web.json_response(status)

    # --- Handler Internal Raft ---
    async def handle_request_vote(self, request: web.Request):
        """Handler untuk RPC /request_vote."""
        try:
            args = await request.json()
            response = await self.raft_node.handle_request_vote(args)
            return web.json_response(response)
        except Exception as e:
             logger.error(f"Error in handle_request_vote: {e}")
             return web.json_response({"error": "Internal server error"}, status=500)

    async def handle_append_entries(self, request: web.Request):
        """Handler untuk RPC /append_entries."""
        try:
            args = await request.json()
            response = await self.raft_node.handle_append_entries(args)
            return web.json_response(response)
        except Exception as e:
             logger.error(f"Error in handle_append_entries: {e}")
             return web.json_response({"error": "Internal server error"}, status=500)


    async def start(self, host: str, port: int):
        """Menjalankan server HTTP."""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        logger.info(f"HTTP Server listening on http://{host}:{port}")
        await site.start()
        # Biarkan server berjalan selamanya (atau sampai dihentikan)
        await asyncio.Event().wait()