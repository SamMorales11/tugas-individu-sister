# server.py
import asyncio
import logging
from aiohttp import web, ClientSession, ClientTimeout, TCPConnector
import json

from consistent_hash import ConsistentHashRing
from queue_node import QueueNode, Message # Import Message juga

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class HTTPServer:
    def __init__(self, node_id: str, self_addr: str, ring: ConsistentHashRing, queue_node: QueueNode):
        self.node_id = node_id
        self.self_addr = self_addr
        self.ring = ring
        self.queue_node = queue_node
        self.app = web.Application()
        # Buat satu ClientSession untuk reuse koneksi
        # Limit koneksi per host agar tidak membanjiri satu node
        connector = TCPConnector(limit_per_host=20)
        self.http_client = ClientSession(connector=connector, timeout=ClientTimeout(total=5)) # Timeout 5 detik
        self.setup_routes()

    async def close_client(self):
        """Menutup aiohttp ClientSession."""
        await self.http_client.close()
        logger.info(f"Node {self.node_id}: HTTP client session closed.")

    def setup_routes(self):
        self.app.router.add_post('/produce', self.handle_produce)
        self.app.router.add_get('/consume', self.handle_consume)
        self.app.router.add_post('/ack', self.handle_acknowledge)
        self.app.router.add_post('/replicate', self.handle_replicate) # <-- ENDPOINT BARU

    async def _forward_request(self, target_node: str, request: web.Request):
        """Meneruskan request ke node yang benar."""
        target_url = f"http://{target_node}{request.path_qs}" # path_qs termasuk query string
        method = request.method
        headers = {k: v for k, v in request.headers.items() if k.lower() != 'host'} # Salin header, buang host
        body = await request.read() # Baca body mentah

        logger.debug(f"Forwarding {method} {request.path_qs} to {target_url}")
        try:
            async with self.http_client.request(method, target_url, headers=headers, data=body) as resp:
                # Kembalikan response dari target node ke klien asli
                resp_body = await resp.read()
                # Perlu hati-hati set header, terutama Content-Type
                resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in ['content-encoding', 'transfer-encoding']}
                return web.Response(body=resp_body, status=resp.status, headers=resp_headers)
        except asyncio.TimeoutError:
            logger.error(f"Timeout forwarding request to {target_url}")
            return web.json_response({"error": "Forwarding timeout"}, status=504) # Gateway Timeout
        except Exception as e:
            logger.error(f"Error forwarding request to {target_url}: {e}", exc_info=True)
            return web.json_response({"error": "Forwarding failed"}, status=502) # Bad Gateway


    async def handle_produce(self, request: web.Request):
        try:
            data = await request.json()
            queue_name = data.get("queue")
            body = data.get("body")
            if not queue_name or body is None: # Cek body juga
                return web.json_response({"error": "Missing 'queue' or 'body'"}, status=400)

            # Tentukan node primer dan replika (2 node berikutnya)
            nodes = self.ring.get_nodes(queue_name, 3) # Ambil 3 node: primer + 2 replika
            target_node = nodes[0] if nodes else None
            logger.info(f"Target nodes for queue '{queue_name}': {nodes}")

            if not target_node:
                 return web.json_response({"error": "No nodes available in the ring"}, status=503)


            if target_node == self.self_addr:
                # Proses di node ini
                message_id, msg_obj = await self.queue_node.produce(queue_name, body)

                # Kirim replikasi ke node lain (jika ada)
                replica_tasks = []
                for replica_node in nodes[1:]: # Mulai dari node kedua
                    if replica_node != self.self_addr: # Jangan kirim ke diri sendiri
                        replica_tasks.append(
                            asyncio.create_task(self._send_replication(replica_node, queue_name, msg_obj))
                        )
                if replica_tasks:
                    await asyncio.gather(*replica_tasks, return_exceptions=True) # Tunggu replikasi (atau handle error)

                return web.json_response({"status": "created", "message_id": message_id}, status=201)
            else:
                # Forward request ke target_node
                return await self._forward_request(target_node, request)

        except json.JSONDecodeError:
             return web.json_response({"error": "Invalid JSON body"}, status=400)
        except Exception as e:
            logger.error(f"Error in handle_produce: {e}", exc_info=True)
            return web.json_response({"error": "Internal server error"}, status=500)

    async def handle_consume(self, request: web.Request):
        queue_name = request.query.get("queue")
        if not queue_name:
            return web.json_response({"error": "Missing 'queue' query parameter"}, status=400)

        target_node = self.ring.get_node(queue_name)
        if not target_node:
             return web.json_response({"error": "No nodes available in the ring"}, status=503)

        if target_node == self.self_addr:
            message = await self.queue_node.consume(queue_name)
            if message:
                return web.json_response(message, status=200)
            else:
                return web.json_response({"message": f"Queue '{queue_name}' is empty"}, status=404)
        else:
             return await self._forward_request(target_node, request)

    async def handle_acknowledge(self, request: web.Request):
        try:
            data = await request.json()
            message_id = data.get("message_id")
            if not message_id:
                return web.json_response({"error": "Missing 'message_id'"}, status=400)

            # Cari tahu node mana yg seharusnya menyimpan state unacked
            # Ini asumsi sederhana: ACK ke node yg sama dg consume
            # TODO: Perlu logika lebih canggih jika node gagal & state pindah
            #       Untuk sementara, kita tidak forward ACK. Klien harus tahu node yg benar.

            success = await self.queue_node.acknowledge(message_id)
            if success:
                return web.json_response({"status": "acknowledged"}, status=200)
            else:
                # Mungkin ACK dikirim ke node yg salah, coba cari node lain? (Kompleks)
                logger.warning(f"ACK for {message_id} failed on node {self.node_id}")
                return web.json_response({"error": "Message ID not found or already acknowledged on this node"}, status=404)

        except json.JSONDecodeError:
             return web.json_response({"error": "Invalid JSON body"}, status=400)
        except Exception as e:
            logger.error(f"Error in handle_acknowledge: {e}", exc_info=True)
            return web.json_response({"error": "Internal server error"}, status=500)

    # --- Endpoint & Logika Replikasi ---
    async def handle_replicate(self, request: web.Request):
        """Menerima pesan replika dari node lain."""
        try:
            data = await request.json()
            queue_name = data.get("queue")
            msg_data = data.get("msg")
            if not queue_name or not msg_data:
                return web.json_response({"error": "Invalid replication request"}, status=400)

            msg = Message.from_dict(msg_data)
            await self.queue_node.replicate(queue_name, msg) # Panggil fungsi di QueueNode
            return web.json_response({"status": "replicated"}, status=200)

        except json.JSONDecodeError:
             return web.json_response({"error": "Invalid JSON body"}, status=400)
        except Exception as e:
             logger.error(f"Error in handle_replicate: {e}", exc_info=True)
             return web.json_response({"error": "Failed to store replicated message"}, status=500)

    async def _send_replication(self, target_node: str, queue_name: str, msg: Message):
        """Mengirim pesan ke node replika."""
        url = f"http://{target_node}/replicate"
        payload = {"queue": queue_name, "msg": msg.to_dict()}
        try:
             async with self.http_client.post(url, json=payload) as resp:
                 if resp.status == 200:
                     logger.info(f"Successfully replicated message {msg.id} to {target_node}")
                 else:
                     logger.warning(f"Failed to replicate message {msg.id} to {target_node}. Status: {resp.status}")
        except Exception as e:
            logger.error(f"Error sending replication of {msg.id} to {target_node}: {e}")
            # TODO: Tambahkan mekanisme retry atau antrean gagal replikasi

    async def start(self, host: str, port: int):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        logger.info(f"HTTP Server listening on http://{host}:{port}")
        await site.start()
        # Biarkan server berjalan (akan dihandle oleh asyncio.gather di main.py)
        while True:
            await asyncio.sleep(3600)