# queue_node.py
import asyncio
import logging
import uuid
import os
import json
import aiofiles
from typing import Dict, List, Optional, Tuple, Set

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s') # Pastikan level DEBUG
logger = logging.getLogger(__name__)

# ... (Class Message dan konstanta LOG_SUFFIX/ACK_SUFFIX tetap sama) ...
LOG_SUFFIX = ".log"
ACK_SUFFIX = ".ack"

class Message:
    def __init__(self, body: str, msg_id: str = None):
        self.id = msg_id if msg_id else str(uuid.uuid4())
        self.body = body
    def to_dict(self) -> Dict: return {"id": self.id, "body": self.body}
    @classmethod
    def from_dict(cls, data: Dict): return cls(body=data.get("body"), msg_id=data.get("id"))


class QueueNode:
    def __init__(self, node_id: str, data_dir: str):
        self.node_id = node_id
        self.data_dir = data_dir
        self.queues: Dict[str, List[Message]] = {}
        self.unacked_messages: Dict[str, Tuple[str, Message]] = {}
        self.log_files: Dict[str, asyncio.StreamWriter] = {}
        self.ack_files: Dict[str, asyncio.StreamWriter] = {}
        self.lock = asyncio.Lock()
        self.acked_ids: Dict[str, Set[str]] = {}

    async def initialize(self):
        os.makedirs(self.data_dir, exist_ok=True)
        await self._recover_state()

    async def _recover_state(self):
        async with self.lock:
            logger.info(f"Node {self.node_id}: Recovering state from {self.data_dir}")
            # Baca ACK files
            ack_files = [f for f in os.listdir(self.data_dir) if f.endswith(ACK_SUFFIX)]
            for ack_filename in ack_files:
                queue_name = ack_filename[:-len(ACK_SUFFIX)]
                self.acked_ids[queue_name] = set()
                try:
                    async with aiofiles.open(os.path.join(self.data_dir, ack_filename), mode='r') as afp:
                        async for line in afp:
                            ack_id = line.strip();
                            if ack_id: self.acked_ids[queue_name].add(ack_id)
                    logger.info(f"Recovered {len(self.acked_ids[queue_name])} acknowledged IDs for queue '{queue_name}'")
                except Exception as e: logger.error(f"Error reading ACK file {ack_filename}: {e}")

            # Baca LOG files
            log_files = [f for f in os.listdir(self.data_dir) if f.endswith(LOG_SUFFIX)]
            for log_filename in log_files:
                queue_name = log_filename[:-len(LOG_SUFFIX)]; recovered_count = 0
                if queue_name not in self.queues: self.queues[queue_name] = []
                acked_set = self.acked_ids.get(queue_name, set())
                try:
                    async with aiofiles.open(os.path.join(self.data_dir, log_filename), mode='r') as afp:
                        async for line in afp:
                            line = line.strip();
                            if not line: continue
                            try:
                                msg_data = json.loads(line); msg = Message.from_dict(msg_data)
                                if msg.id not in acked_set: self.queues[queue_name].append(msg); recovered_count += 1
                            except json.JSONDecodeError: logger.warning(f"Skipping invalid JSON line in {log_filename}: {line}")
                    logger.info(f"Recovered {recovered_count} active messages for queue '{queue_name}'")
                except Exception as e: logger.error(f"Error reading log file {log_filename}: {e}")

    async def _get_log_file(self, queue_name: str):
        if queue_name not in self.log_files or getattr(self.log_files[queue_name], '_file', None) is None or self.log_files[queue_name]._file.closed:
             filepath = os.path.join(self.data_dir, f"{queue_name}{LOG_SUFFIX}")
             self.log_files[queue_name] = await aiofiles.open(filepath, mode='a')
        return self.log_files[queue_name]

    async def _get_ack_file(self, queue_name: str):
         if queue_name not in self.ack_files or getattr(self.ack_files[queue_name], '_file', None) is None or self.ack_files[queue_name]._file.closed:
             filepath = os.path.join(self.data_dir, f"{queue_name}{ACK_SUFFIX}")
             self.ack_files[queue_name] = await aiofiles.open(filepath, mode='a')
         return self.ack_files[queue_name]


    async def _persist_message(self, queue_name: str, msg: Message):
        try:
            log_file = await self._get_log_file(queue_name)
            msg_json = json.dumps(msg.to_dict())
            await log_file.write(msg_json + '\n'); await log_file.flush()
            logger.debug(f"Node {self.node_id}: Persisted message {msg.id} to {log_file.name}")
        except Exception as e: logger.error(f"Node {self.node_id}: Failed to persist message {msg.id}: {e}")

    async def _persist_ack(self, queue_name: str, message_id: str):
        try:
            ack_file = await self._get_ack_file(queue_name)
            await ack_file.write(message_id + '\n'); await ack_file.flush()
            logger.debug(f"Node {self.node_id}: Persisted ACK for {message_id} to {ack_file.name}")
        except Exception as e: logger.error(f"Node {self.node_id}: Failed to persist ACK for {message_id}: {e}")

    async def produce(self, queue_name: str, body: str, is_replica: bool = False) -> Tuple[str, Message]:
        async with self.lock:
            msg = Message(body); await self._persist_message(queue_name, msg)
            if queue_name not in self.queues: self.queues[queue_name] = []
            self.queues[queue_name].append(msg)
            log_prefix = "(Replica) " if is_replica else ""
            logger.info(f"Node {self.node_id}: {log_prefix}Message {msg.id} added to queue '{queue_name}' (persisted & in-memory)")
            return msg.id, msg

    async def consume(self, queue_name: str) -> Optional[Dict]:
        async with self.lock:
            if queue_name not in self.queues or not self.queues[queue_name]: return None
            msg = self.queues[queue_name].pop(0)
            self.unacked_messages[msg.id] = (queue_name, msg)
            logger.debug(f"Node {self.node_id}: Message {msg.id} from '{queue_name}' moved to unacked. Current unacked IDs: {list(self.unacked_messages.keys())}")
            return msg.to_dict()

    async def acknowledge(self, message_id: str) -> bool:
        """Konfirmasi pesan, simpan ACK ke disk."""
        async with self.lock:
            # === LOG TAMBAHAN YANG SANGAT DETAIL ===
            current_unacked_dict_repr = repr(self.unacked_messages) # Representasi detail dictionary
            logger.debug(f"Node {self.node_id}: ACK received for ID '{message_id}' (type: {type(message_id)}).")
            logger.debug(f"Node {self.node_id}: Current unacked_messages dictionary: {current_unacked_dict_repr}")
            # ======================================

            if message_id in self.unacked_messages:
                queue_name, msg = self.unacked_messages.pop(message_id)
                await self._persist_ack(queue_name, message_id)
                if queue_name not in self.acked_ids: self.acked_ids[queue_name] = set()
                self.acked_ids[queue_name].add(message_id)
                logger.info(f"Node {self.node_id}: Message {msg.id} from '{queue_name}' acknowledged (persisted)")
                return True
            else:
                logger.warning(f"Node {self.node_id}: ACK FAILED. ID '{message_id}' NOT FOUND in unacked list.")
                # Log tipe kunci dictionary untuk perbandingan
                key_types = [type(k) for k in self.unacked_messages.keys()]
                logger.debug(f"Node {self.node_id}: Types of keys in unacked_messages: {key_types}")
                return False

    async def replicate(self, queue_name: str, msg: Message):
        logger.info(f"Node {self.node_id}: Received replica for message {msg.id} in queue '{queue_name}'")
        await self.produce(queue_name, msg.body, is_replica=True)

    async def close_files(self):
        async with self.lock:
            closed_count = 0
            for queue_name in list(self.log_files.keys()):
                f = self.log_files.pop(queue_name)
                # Perbaikan pengecekan handle file aiofiles
                if f and getattr(f, 'fileno', lambda: -1)() != -1:
                   try: await f.close(); closed_count += 1
                   except: pass # Abaikan error saat menutup
            for queue_name in list(self.ack_files.keys()):
                f = self.ack_files.pop(queue_name)
                if f and getattr(f, 'fileno', lambda: -1)() != -1:
                   try: await f.close(); closed_count += 1
                   except: pass
            if closed_count > 0:
                 logger.info(f"Node {self.node_id}: Closed {closed_count} log/ack files.")