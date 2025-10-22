# raft_node.py
import asyncio
import random
import logging
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
import aiohttp # Untuk RPC nanti

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NodeState(Enum):
    FOLLOWER = 1
    CANDIDATE = 2
    LEADER = 3

class RaftNode:
    def __init__(self, node_id: str, peers: List[str], fsm: Any):
        self.node_id = node_id
        self.peers = [p for p in peers if p != self.node_id] # Alamat peers lain
        self.fsm = fsm # State machine (Lock Manager)

        self.state = NodeState.FOLLOWER
        self.current_term = 0
        self.voted_for: Optional[str] = None
        self.log: List[Dict] = [{"term": 0, "command": None}] # Log dimulai dgn dummy
        self.commit_index = 0
        self.last_applied = 0

        # State volatile leader (direset saat jadi leader)
        self.next_index: Dict[str, int] = {}
        self.match_index: Dict[str, int] = {}

        self.leader_id: Optional[str] = None
        self.election_timeout_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None

        # Lock untuk melindungi state internal Raft
        self.raft_lock = asyncio.Lock()

    async def start(self):
        """Memulai node Raft."""
        logger.info(f"Node {self.node_id} starting as Follower.")
        await self._reset_election_timer()

    async def _reset_election_timer(self):
        """Mereset timer pemilihan."""
        if self.election_timeout_task:
            self.election_timeout_task.cancel()

        timeout = random.uniform(0.150, 0.300) # Timeout acak (detik)
        self.election_timeout_task = asyncio.create_task(self._election_timeout_handler(timeout))
        # logger.debug(f"Node {self.node_id} election timer reset to {timeout:.3f}s")

    async def _election_timeout_handler(self, timeout: float):
        """Handler saat timer pemilihan habis."""
        await asyncio.sleep(timeout)
        async with self.raft_lock:
             # Hanya mulai pemilihan jika masih follower/candidate (bukan leader)
            if self.state != NodeState.LEADER:
                logger.info(f"Node {self.node_id} election timeout reached. Starting election.")
                await self._start_election()
            # Reset lagi timer setelah selesai (apapun hasilnya)
            await self._reset_election_timer()


    async def _start_election(self):
        """Memulai proses pemilihan baru (internal, lock dipegang)."""
        self.state = NodeState.CANDIDATE
        self.current_term += 1
        self.voted_for = self.node_id
        votes_received = 1
        logger.info(f"Node {self.node_id} became Candidate for term {self.current_term}.")

        # Kirim RequestVote RPC ke semua peers
        tasks = []
        last_log_index = len(self.log) - 1
        last_log_term = self.log[last_log_index]["term"]
        args = {
            "term": self.current_term,
            "candidate_id": self.node_id,
            "last_log_index": last_log_index,
            "last_log_term": last_log_term,
        }
        for peer in self.peers:
            tasks.append(asyncio.create_task(self._send_rpc(peer, "/request_vote", args)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, dict) and result.get("vote_granted"):
                votes_received += 1
            # Handle jika term kita lebih rendah
            elif isinstance(result, dict) and result.get("term", 0) > self.current_term:
                logger.info(f"Node {self.node_id} discovered higher term {result['term']}. Reverting to Follower.")
                self.current_term = result["term"]
                self.state = NodeState.FOLLOWER
                self.voted_for = None
                await self._cancel_heartbeat() # Hentikan heartbeat jika sempat jadi leader
                return # Stop proses election

        # Cek kemenangan
        majority = (len(self.peers) + 1) // 2 + 1
        if self.state == NodeState.CANDIDATE and votes_received >= majority:
            logger.info(f"Node {self.node_id} WON election with {votes_received} votes for term {self.current_term}.")
            await self._become_leader()
        elif self.state == NodeState.CANDIDATE: # Jika tidak menang dan tidak revert ke follower
             logger.info(f"Node {self.node_id} LOST election with {votes_received} votes. Returning to Follower.")
             self.state = NodeState.FOLLOWER # Kembali jadi Follower


    async def _become_leader(self):
        """Transisi menjadi Leader (internal, lock dipegang)."""
        self.state = NodeState.LEADER
        self.leader_id = self.node_id
        last_log_index = len(self.log) - 1
        self.next_index = {peer: last_log_index + 1 for peer in self.peers}
        self.match_index = {peer: 0 for peer in self.peers}

        # Hentikan timer pemilihan
        if self.election_timeout_task:
            self.election_timeout_task.cancel()

        # Mulai kirim heartbeat periodik
        await self._start_heartbeat()
        # Kirim heartbeat awal segera
        await self._send_heartbeats()

    async def _start_heartbeat(self):
        """Mulai task periodik untuk mengirim heartbeat."""
        await self._cancel_heartbeat() # Pastikan hanya satu yg jalan
        heartbeat_interval = 0.050 # 50ms
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop(heartbeat_interval))
        logger.info(f"Node {self.node_id} (Leader) starting heartbeats.")

    async def _heartbeat_loop(self, interval: float):
        """Loop pengiriman heartbeat."""
        while True:
            await asyncio.sleep(interval)
            async with self.raft_lock:
                if self.state != NodeState.LEADER:
                    break # Berhenti jika bukan leader lagi
                await self._send_heartbeats()
        logger.info(f"Node {self.node_id} stopping heartbeats.")

    async def _cancel_heartbeat(self):
         if self.heartbeat_task:
            self.heartbeat_task.cancel()
            self.heartbeat_task = None


    async def _send_heartbeats(self):
        """Mengirim AppendEntries (kosong) sebagai heartbeat (internal, lock dipegang)."""
        logger.debug(f"Node {self.node_id} (Leader) sending heartbeats for term {self.current_term}.")
        args = {
            "term": self.current_term,
            "leader_id": self.node_id,
            "prev_log_index": 0, # Placeholder
            "prev_log_term": 0,  # Placeholder
            "entries": [],
            "leader_commit": self.commit_index,
        }
        tasks = []
        for peer in self.peers:
            # TODO: Sesuaikan prevLogIndex/Term per peer
            tasks.append(asyncio.create_task(self._send_rpc(peer, "/append_entries", args)))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Handle balasan (misal, revert ke follower jika ada term lebih tinggi)
        for result in results:
            if isinstance(result, dict) and result.get("term", 0) > self.current_term:
                 logger.info(f"Node {self.node_id} discovered higher term {result['term']} from heartbeat reply. Reverting to Follower.")
                 self.current_term = result["term"]
                 self.state = NodeState.FOLLOWER
                 self.voted_for = None
                 await self._cancel_heartbeat()
                 await self._reset_election_timer() # Mulai timer lagi sbg follower
                 return


    async def client_request(self, command: Dict) -> Tuple[bool, Optional[str]]:
        """Menerima permintaan dari klien."""
        async with self.raft_lock:
            if self.state != NodeState.LEADER:
                return False, self.leader_id # Bukan leader, kembalikan leader ID jika tahu

            # 1. Tambah command ke log leader
            log_entry = {"term": self.current_term, "command": command}
            self.log.append(log_entry)
            log_index = len(self.log) - 1
            logger.info(f"Node {self.node_id} (Leader) appended command to log at index {log_index}")

            # 2. Kirim AppendEntries ke followers (disederhanakan, kirim segera)
            args = {
                "term": self.current_term,
                "leader_id": self.node_id,
                 # TODO: Logika prevLogIndex/Term yg benar per follower
                "prev_log_index": log_index -1,
                "prev_log_term": self.log[log_index-1]["term"],
                "entries": [log_entry],
                "leader_commit": self.commit_index,
            }
            tasks = []
            for peer in self.peers:
                tasks.append(asyncio.create_task(self._send_rpc(peer, "/append_entries", args)))

            # Tunggu mayoritas
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count = 1 # Diri sendiri
            for result in results:
                 if isinstance(result, dict) and result.get("success"):
                     success_count += 1
                     # TODO: Update matchIndex dan nextIndex

            # 3. Jika mayoritas, commit & apply
            majority = (len(self.peers) + 1) // 2 + 1
            if success_count >= majority:
                 if log_index > self.commit_index and self.log[log_index]["term"] == self.current_term:
                    self.commit_index = log_index
                    logger.info(f"Node {self.node_id} (Leader) committed index {self.commit_index}")
                    # Apply ke FSM
                    result_fsm = await self.fsm.apply_command(command)
                    self.last_applied = self.commit_index # Disederhanakan
                    return True, result_fsm # Berhasil & kembalikan hasil FSM
            else:
                 logger.warning(f"Node {self.node_id} (Leader) failed to replicate log index {log_index} to majority.")

            return False, "replication_failed" # Gagal replikasi


    # --- Handler RPC ---
    async def handle_request_vote(self, args: Dict) -> Dict:
        """Menangani RPC RequestVote dari kandidat lain."""
        async with self.raft_lock:
            response = {"term": self.current_term, "vote_granted": False}
            candidate_term = args.get("term", 0)

            if candidate_term < self.current_term:
                logger.info(f"Node {self.node_id} denying vote to {args.get('candidate_id')}: lower term {candidate_term} < {self.current_term}")
                return response # Term kandidat lebih rendah

            if candidate_term > self.current_term:
                logger.info(f"Node {self.node_id} received RV from higher term {candidate_term}. Reverting to Follower.")
                self.current_term = candidate_term
                self.state = NodeState.FOLLOWER
                self.voted_for = None
                await self._cancel_heartbeat()

            # Berikan suara jika term sama, belum vote, dan log kandidat up-to-date
            candidate_log_ok = True # TODO: Implementasi pengecekan log up-to-date (Section 5.4.1)
            if self.current_term == candidate_term and \
               (self.voted_for is None or self.voted_for == args.get("candidate_id")) and \
               candidate_log_ok:
                    logger.info(f"Node {self.node_id} granting vote to {args.get('candidate_id')} for term {self.current_term}")
                    self.voted_for = args.get("candidate_id")
                    response["vote_granted"] = True
                    # Reset timer KITA karena kita memberi vote
                    await self._reset_election_timer()
            else:
                 logger.info(f"Node {self.node_id} denying vote to {args.get('candidate_id')}: voted_for={self.voted_for}, log_ok={candidate_log_ok}")


            return response


    async def handle_append_entries(self, args: Dict) -> Dict:
        """Menangani RPC AppendEntries dari leader."""
        async with self.raft_lock:
            response = {"term": self.current_term, "success": False}
            leader_term = args.get("term", 0)

            if leader_term < self.current_term:
                logger.info(f"Node {self.node_id} rejecting AE from {args.get('leader_id')}: lower term {leader_term} < {self.current_term}")
                return response # Term leader lebih rendah

            # Jika menerima AE (termasuk heartbeat), reset timer pemilihan
            await self._reset_election_timer()

            if leader_term > self.current_term:
                 logger.info(f"Node {self.node_id} received AE from higher term {leader_term}. Updating term and becoming Follower.")
                 self.current_term = leader_term
                 self.state = NodeState.FOLLOWER
                 self.voted_for = None
                 await self._cancel_heartbeat()

            # Jika kita Candidate, kembali jadi Follower krn ada leader yg sah
            if self.state == NodeState.CANDIDATE:
                 logger.info(f"Node {self.node_id} (Candidate) received AE from Leader {args.get('leader_id')}. Reverting to Follower.")
                 self.state = NodeState.FOLLOWER

            # Set leader ID
            self.leader_id = args.get("leader_id")

            # TODO: Implementasi logika pengecekan konsistensi log (Section 5.3)
            log_ok = True

            if log_ok:
                response["success"] = True
                # TODO: Append entries ke log lokal jika ada
                entries = args.get("entries", [])
                if entries:
                     # Hapus log yg konflik, lalu append yg baru
                     pass

                # Update commit index jika leader commit > commit index kita
                leader_commit = args.get("leader_commit", 0)
                if leader_commit > self.commit_index:
                    # commit_index = min(leader_commit, index_of_last_new_entry)
                    new_commit_index = min(leader_commit, len(self.log) - 1) # Disederhanakan
                    if new_commit_index > self.commit_index:
                         self.commit_index = new_commit_index
                         logger.info(f"Node {self.node_id} updated commit_index to {self.commit_index}")
                         # Apply log ke FSM (di background task?)
                         # Note: apply harusnya terjadi di loop terpisah yg memonitor commit_index
                         # while self.last_applied < self.commit_index:
                         #      self.last_applied += 1
                         #      command = self.log[self.last_applied]["command"]
                         #      await self.fsm.apply_command(command)
                         #      logger.info(f"Node {self.node_id} applied log index {self.last_applied}")

            return response

    async def _send_rpc(self, target_node_addr: str, path: str, data: Dict) -> Optional[Dict]:
        """Helper untuk mengirim RPC ke node lain."""
        # Alamat peer lengkap (misal: http://127.0.0.1:7001)
        # Kita asumsikan format peers adalah "host:port" untuk raft, API di port+1000
        try:
            host, raft_port_str = target_node_addr.split(':')
            api_port = int(raft_port_str) + 1000 # Konvensi: API di port+1000
            url = f"http://{host}:{api_port}{path}"

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=0.1)) as session: # Timeout pendek
                async with session.post(url, json=data) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.warning(f"Node {self.node_id} received non-200 status {response.status} from {target_node_addr} for {path}")
                        return None
        except asyncio.TimeoutError:
             logger.warning(f"Node {self.node_id} timeout sending RPC {path} to {target_node_addr}")
             return None
        except aiohttp.ClientConnectorError as e:
            logger.warning(f"Node {self.node_id} connection error sending RPC {path} to {target_node_addr}: {e}")
            return None
        except Exception as e:
            logger.error(f"Node {self.node_id} unexpected error sending RPC {path} to {target_node_addr}: {e}")
            return None

    async def get_status(self) -> Dict:
         """Mengembalikan status internal node."""
         async with self.raft_lock:
             return {
                 "node_id": self.node_id,
                 "state": self.state.name,
                 "term": self.current_term,
                 "leader_id": self.leader_id,
                 "commit_index": self.commit_index,
                 "last_applied": self.last_applied,
                 "log_length": len(self.log)
             }