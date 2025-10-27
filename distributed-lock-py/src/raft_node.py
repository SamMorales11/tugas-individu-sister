# raft_node.py
import asyncio
import random
import logging
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
import aiohttp

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NodeState(Enum): FOLLOWER = 1; CANDIDATE = 2; LEADER = 3

class RaftNode:
    def __init__(self, node_id: str, peers: List[str], fsm: Any, peer_http_map: Dict[str, str]):
        self.node_id = node_id
        self.peers = peers
        self.fsm = fsm
        self.peer_http_map = peer_http_map
        self.state = NodeState.FOLLOWER
        self.current_term = 0
        self.voted_for: Optional[str] = None
        self.log: List[Dict] = [{"term": 0, "command": None}]
        self.commit_index = 0
        self.last_applied = 0
        self.next_index: Dict[str, int] = {}
        self.match_index: Dict[str, int] = {}
        self.leader_id: Optional[str] = None
        self.election_timeout_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.raft_lock = asyncio.Lock()

    async def start(self):
        logger.info(f"Node {self.node_id} starting as Follower.")
        await self._reset_election_timer()

    async def _reset_election_timer(self):
        if self.election_timeout_task:
            self.election_timeout_task.cancel()
        # --- ELECTION TIMEOUT LEBIH LAMA ---
        # Sekarang 750ms - 1500ms (0.75 - 1.5 detik)
        timeout = random.uniform(0.750, 1.500)
        # -----------------------------------
        logger.debug(f"Node {self.node_id}: Resetting election timer to {timeout:.3f}s")
        self.election_timeout_task = asyncio.create_task(self._election_timeout_handler(timeout))

    async def _election_timeout_handler(self, timeout: float):
        await asyncio.sleep(timeout)
        should_elect = False
        async with self.raft_lock:
             if self.state != NodeState.LEADER and self.election_timeout_task and not self.election_timeout_task.cancelled():
                 logger.info(f"Node {self.node_id} election timeout reached ({timeout:.3f}s). Starting election.")
                 should_elect = True
        if should_elect:
             asyncio.create_task(self._start_election_wrapper())

    async def _start_election_wrapper(self):
         await self._start_election()
         async with self.raft_lock:
              if self.state != NodeState.LEADER:
                   await self._reset_election_timer()

    # --- PERBAIKAN: _start_election diubah untuk melepaskan lock sebelum await ---
    async def _start_election(self):
        current_term_for_election = -1
        last_log_index = -1
        last_log_term = -1
        peers_to_request = []

        async with self.raft_lock:
            if self.state == NodeState.LEADER: 
                return
            
            self.state = NodeState.CANDIDATE
            self.current_term += 1
            current_term_for_election = self.current_term
            self.voted_for = self.node_id
            
            logger.info(f"Node {self.node_id} became Candidate for term {self.current_term}.")
            
            last_log_index = len(self.log) - 1
            last_log_term = self.log[last_log_index]["term"]
            peers_to_request = list(self.peers)

        # --- PERBAIKAN: RPC (await) dilakukan di luar lock ---
        args = {
            "term": current_term_for_election,
            "candidate_id": self.node_id,
            "last_log_index": last_log_index,
            "last_log_term": last_log_term,
        }
        
        tasks = []
        for peer in peers_to_request:
            tasks.append(asyncio.create_task(self._send_rpc(peer, "/request_vote", args)))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)

        highest_term_seen = current_term_for_election
        current_votes = 1
        for result in results:
            if isinstance(result, dict):
                if result.get("vote_granted"): 
                    current_votes += 1
                if result.get("term", 0) > highest_term_seen: 
                    highest_term_seen = result.get("term", 0)
            elif isinstance(result, Exception): 
                logger.warning(f"Node {self.node_id}: RPC during election failed: {result}")

        won_election = False
        revert_to_follower = False
        
        async with self.raft_lock:
            if self.current_term > current_term_for_election:
                 logger.info(f"Node {self.node_id}: Election result for term {current_term_for_election} ignored, current term is {self.current_term}")
                 return

            if highest_term_seen > self.current_term:
                 logger.info(f"Node {self.node_id} discovered higher term {highest_term_seen} during election. Reverting to Follower.")
                 self.current_term = highest_term_seen
                 self.state = NodeState.FOLLOWER
                 self.voted_for = None
                 revert_to_follower = True
            
            majority = (len(self.peers) + 1) // 2 + 1
            if self.state == NodeState.CANDIDATE and self.current_term == current_term_for_election and current_votes >= majority:
                # --- PERBAIKAN: Menjadi leader, set state di dalam lock ---
                self.state = NodeState.LEADER
                self.leader_id = self.node_id
                logger.info(f"Node {self.node_id}: === BECAME LEADER for term {self.current_term} ===")
                
                # Inisialisasi state leader (sinkron)
                last_log_index = len(self.log) - 1
                self.next_index = {peer: last_log_index + 1 for peer in self.peers}
                self.match_index = {peer: 0 for peer in self.peers}
                won_election = True # Tandai untuk melakukan async work
            
            elif self.state == NodeState.CANDIDATE and self.current_term == current_term_for_election:
                 logger.info(f"Node {self.node_id} LOST election with {current_votes} votes for term {self.current_term}. Returning to Follower.")
                 self.state = NodeState.FOLLOWER

        # --- PERBAIKAN: Await (async work) dilakukan di luar lock ---
        if revert_to_follower:
            await self._cancel_heartbeat()
            # Timer akan di-reset oleh _start_election_wrapper
            
        if won_election:
            if self.election_timeout_task: 
                self.election_timeout_task.cancel()
            await self._start_heartbeat() # Ini akan memanggil _send_heartbeats

    # --- PERBAIKAN: Fungsi _become_leader dihapus karena logikanya dipindah ke _start_election ---

    async def _start_heartbeat(self):
        await self._cancel_heartbeat()
        # --- HEARTBEAT INTERVAL LEBIH CEPAT ---
        heartbeat_interval = 0.150 # Heartbeat 150ms
        # -------------------------------------
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop(heartbeat_interval))
        logger.info(f"Node {self.node_id} (Leader) starting heartbeats.")

    async def _heartbeat_loop(self, interval: float):
        while True:
            await asyncio.sleep(interval)
            should_send = False
            async with self.raft_lock:
                 if self.state == NodeState.LEADER: should_send = True
            if should_send: 
                await self._send_heartbeats() # Panggil _send_heartbeats (async)
            else: 
                break
        logger.info(f"Node {self.node_id} stopping heartbeats.")

    async def _cancel_heartbeat(self):
         if self.heartbeat_task: 
             self.heartbeat_task.cancel()
             self.heartbeat_task = None

    async def _send_heartbeats(self):
        logger.debug(f"Node {self.node_id} (Leader) sending heartbeats for term {self.current_term}.")
        tasks = []
        highest_term_seen = -1
        current_term_for_hb = -1
        
        async with self.raft_lock:
             if self.state != NodeState.LEADER: 
                 return
             current_term_for_hb = self.current_term
             highest_term_seen = self.current_term
             
             args_template = { 
                 "term": current_term_for_hb, 
                 "leader_id": self.node_id, 
                 "leader_commit": self.commit_index 
             }
             for peer in self.peers:
                 # TODO: Log logic yang benar harus ada di sini,
                 # tapi untuk heartbeat kita kirim log kosong
                 peer_args = args_template.copy()
                 peer_args["prev_log_index"] = 0 # Logika heartbeat disederhanakan
                 peer_args["prev_log_term"] = 0  # Logika heartbeat disederhanakan
                 peer_args["entries"] = []
                 tasks.append(asyncio.create_task(self._send_rpc(peer, "/append_entries", peer_args)))
        
        # --- PERBAIKAN: Await RPC di luar lock ---
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, dict) and result.get("term", 0) > highest_term_seen: 
                highest_term_seen = result.get("term", 0)
        
        revert_to_follower = False
        if highest_term_seen > current_term_for_hb:
            async with self.raft_lock:
                 if highest_term_seen > self.current_term:
                      logger.info(f"Node {self.node_id} discovered higher term {highest_term_seen} from heartbeat reply. Reverting to Follower.")
                      self.current_term = highest_term_seen
                      self.state = NodeState.FOLLOWER
                      self.voted_for = None
                      revert_to_follower = True

        # --- PERBAIKAN: Await (async work) di luar lock ---
        if revert_to_follower:
            await self._cancel_heartbeat()
            await self._reset_election_timer()

    # --- PERBAIKAN: client_request diubah untuk melepaskan lock sebelum await ---
    async def client_request(self, command: Dict) -> Tuple[bool, Optional[str]]:
        current_term_when_started = -1
        log_index = -1
        tasks = []
        
        async with self.raft_lock:
            if self.state != NodeState.LEADER: 
                return False, self.leader_id
            
            current_term_when_started = self.current_term
            log_entry = {"term": self.current_term, "command": command}
            self.log.append(log_entry)
            log_index = len(self.log) - 1
            logger.info(f"Node {self.node_id} (Leader) appended command {command.get('operation')}-{command.get('lock_name')} to log at index {log_index}")
            
            args_template = { 
                "term": self.current_term, 
                "leader_id": self.node_id, 
                "leader_commit": self.commit_index, 
            }
            for peer in self.peers:
                 peer_args = args_template.copy()
                 peer_args["prev_log_index"] = log_index - 1
                 peer_args["prev_log_term"] = self.log[log_index-1]["term"]
                 peer_args["entries"] = [log_entry]
                 tasks.append(asyncio.create_task(self._send_rpc(peer, "/append_entries", peer_args)))

        # --- PERBAIKAN: Await RPC di luar lock ---
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = 1
        highest_term_seen = current_term_when_started
        for result in results:
             if isinstance(result, dict):
                  if result.get("success"): 
                      success_count += 1
                  if result.get("term", 0) > highest_term_seen: 
                      highest_term_seen = result.get("term", 0)

        command_to_apply = None
        revert_to_follower = False
        replication_failed = False
        unknown_error = False
        result_fsm = None

        async with self.raft_lock:
            if self.current_term != current_term_when_started or self.state != NodeState.LEADER:
                 logger.warning(f"Node {self.node_id}: Term changed or lost leadership during replication for index {log_index}. Aborting commit.")
                 return False, self.leader_id

            if highest_term_seen > self.current_term:
                logger.info(f"Node {self.node_id} discovered higher term {highest_term_seen} during replication. Reverting to Follower.")
                self.current_term = highest_term_seen
                self.state = NodeState.FOLLOWER
                self.voted_for = None
                revert_to_follower = True
            
            majority = (len(self.peers) + 1) // 2 + 1
            if not revert_to_follower and success_count >= majority:
                 if log_index > self.commit_index and self.log[log_index]["term"] == self.current_term:
                    self.commit_index = log_index
                    logger.info(f"Node {self.node_id} (Leader) committed index {self.commit_index}")
                    
                    # Tandai untuk apply FSM
                    command_to_apply = command
                    self.last_applied = self.commit_index
                    
                 elif log_index <= self.commit_index:
                     logger.warning(f"Node {self.node_id} (Leader): Re-applying already committed index {log_index}.")
                     # Tetap panggil FSM jika sudah ter-commit tapi belum di-apply (kasus aneh)
                     if self.last_applied < log_index:
                        command_to_apply = command
                        self.last_applied = log_index
                     else:
                        # Jika sudah di-apply, kita perlu tahu hasil sebelumnya,
                        # tapi kita tidak menyimpannya. Untuk simplicity, kita anggap sukses.
                        # Dalam implementasi nyata, FSM harus idempoten.
                        result_fsm = "already_applied_presumed_success"
            
            elif not revert_to_follower:
                 logger.warning(f"Node {self.node_id} (Leader) failed to replicate log index {log_index} to majority ({success_count}/{majority}).")
                 replication_failed = True
            
            else:
                 unknown_error = True # Seharusnya tidak ke sini

        # --- PERBAIKAN: Await (FSM/Timer) dilakukan di luar lock ---
        if revert_to_follower:
            await self._cancel_heartbeat()
            await self._reset_election_timer()
            return False, self.leader_id
            
        if command_to_apply:
            result_fsm = await self.fsm.apply_command(command_to_apply)
            return True, result_fsm
            
        if result_fsm: # Kasus "already_applied"
            return True, result_fsm

        if replication_failed:
            return False, "replication_failed"

        return False, "unknown_error_in_request"

    # --- PERBAIKAN: handle_request_vote diubah untuk melepaskan lock sebelum await ---
    async def handle_request_vote(self, args: Dict) -> Dict:
        needs_timer_reset = False
        needs_heartbeat_cancel = False
        
        async with self.raft_lock:
            response = {"term": self.current_term, "vote_granted": False}
            candidate_term = args.get("term", 0)
            
            if candidate_term < self.current_term:
                logger.info(f"Node {self.node_id} denying vote to {args.get('candidate_id')}: lower term {candidate_term} < {self.current_term}")
            else:
                if candidate_term > self.current_term:
                    logger.info(f"Node {self.node_id} received RV from higher term {candidate_term}. Reverting to Follower.")
                    self.current_term = candidate_term
                    self.state = NodeState.FOLLOWER
                    self.voted_for = None
                    needs_heartbeat_cancel = True # Tandai untuk async work
                    needs_timer_reset = True      # Tandai untuk async work

                candidate_log_ok = True # TODO: Implement log check (args["last_log_index"] vs len(self.log)-1)
                
                if self.voted_for is None or self.voted_for == args.get("candidate_id"):
                    if candidate_log_ok:
                        logger.info(f"Node {self.node_id} granting vote to {args.get('candidate_id')} for term {self.current_term}")
                        self.voted_for = args.get("candidate_id")
                        response["vote_granted"] = True
                        needs_timer_reset = True # Reset timer jika kita memberi vote
                    else: 
                        logger.info(f"Node {self.node_id} denying vote to {args.get('candidate_id')}: log not up-to-date")
                else: 
                    logger.info(f"Node {self.node_id} denying vote to {args.get('candidate_id')}: already voted for {self.voted_for}")

            response["term"] = self.current_term
            # Lock dilepas di sini
        
        # --- PERBAIKAN: Await (async work) dilakukan di luar lock ---
        if needs_heartbeat_cancel:
            await self._cancel_heartbeat()
        if needs_timer_reset:
            await self._reset_election_timer()
            
        return response

    # --- PERBAIKAN: handle_append_entries diubah untuk melepaskan lock sebelum await ---
    async def handle_append_entries(self, args: Dict) -> Dict:
        needs_timer_reset = False
        needs_heartbeat_cancel = False
        commands_to_apply = [] # Bug fix: followers harus apply commit

        async with self.raft_lock:
            response = {"term": self.current_term, "success": False}
            leader_term = args.get("term", 0)
            
            if leader_term < self.current_term:
                logger.info(f"Node {self.node_id} rejecting AE from {args.get('leader_id')}: lower term {leader_term} < {self.current_term}")
                return response

            # Jika kita menerima AE, kita pasti harus reset timer
            needs_timer_reset = True

            if leader_term >= self.current_term:
                 if leader_term > self.current_term or self.state == NodeState.CANDIDATE:
                    logger.info(f"Node {self.node_id} received AE term {leader_term}. Updating term/state. Becoming Follower.")
                    self.current_term = leader_term
                    self.state = NodeState.FOLLOWER
                    self.voted_for = None
                    needs_heartbeat_cancel = True # Tandai untuk async work
                 
                 self.leader_id = args.get("leader_id")

            log_ok = True # TODO: Implement log consistency check (prev_log_index, prev_log_term)
            
            if log_ok:
                response["success"] = True
                entries = args.get("entries", [])
                if entries:
                     # TODO: Log truncation logic harus ada di sini
                     self.log.extend(entries)
                     logger.info(f"Node {self.node_id}: Appended {len(entries)} entries from leader. New log length: {len(self.log)}")
                
                leader_commit = args.get("leader_commit", 0)
                if leader_commit > self.commit_index:
                    new_commit_index = min(leader_commit, len(self.log) - 1)
                    if new_commit_index > self.commit_index:
                         self.commit_index = new_commit_index
                         logger.info(f"Node {self.node_id} updated commit_index to {self.commit_index}")
                         
                         # --- PERBAIKAN (Bug Fix): Follower harus apply command ---
                         if self.commit_index > self.last_applied:
                             start_idx = self.last_applied + 1
                             end_idx = self.commit_index + 1
                             commands_to_apply = [e["command"] for e in self.log[start_idx:end_idx] if e["command"]]
                             self.last_applied = self.commit_index
            else: 
                logger.warning(f"Node {self.node_id} log consistency check failed for AE from {args.get('leader_id')}")
            
            response["term"] = self.current_term
            # Lock dilepas di sini

        # --- PERBAIKAN: Await (async work) dilakukan di luar lock ---
        if needs_heartbeat_cancel:
            await self._cancel_heartbeat()
        if needs_timer_reset:
            await self._reset_election_timer()
            
        # --- PERBAIKAN (Bug Fix): Jalankan apply FSM di luar lock ---
        if commands_to_apply:
            logger.info(f"Node {self.node_id} (Follower) applying {len(commands_to_apply)} committed entries.")
            for cmd in commands_to_apply:
                await self.fsm.apply_command(cmd)

        return response

    async def _send_rpc(self, target_node_raft_addr: str, path: str, data: Dict) -> Optional[Dict]:
        target_http_addr = self.peer_http_map.get(target_node_raft_addr)
        if not target_http_addr:
            logger.error(f"Node {self.node_id} cannot find HTTP address for Raft peer {target_node_raft_addr}"); return None
        
        url = f"http://{target_http_addr}{path}"
        logger.debug(f"Node {self.node_id}: Sending RPC {path} to {url} (target raft: {target_node_raft_addr})")
        
        try:
            # Timeout RPC tetap 2 detik
            timeout = aiohttp.ClientTimeout(total=2.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=data) as response:
                    if response.status == 200:
                        try: 
                            return await response.json()
                        except Exception as e: 
                            logger.error(f"Node {self.node_id}: Failed to decode JSON response from {url}: {e}")
                            return None
                    else:
                        logger.warning(f"Node {self.node_id} received non-200 status {response.status} from {url} for {path}")
                        return None
        except asyncio.TimeoutError:
             logger.warning(f"Node {self.node_id} timeout sending RPC {path} to {url}")
             return None
        except aiohttp.ClientConnectorError as e: 
             logger.warning(f"Node {self.node_id} connection error sending RPC {path} to {url}: {e}")
             return None # Kurangi noise
        except Exception as e:
            logger.error(f"Node {self.node_id} unexpected error sending RPC {path} to {url}: {e}")
            return None

    async def get_status(self) -> Dict:
         async with self.raft_lock:
             # Fungsi ini aman karena tidak melakukan 'await' di dalam lock
             return { 
                 "node_id": self.node_id, 
                 "state": self.state.name, 
                 "term": self.current_term, 
                 "leader_id": self.leader_id, 
                 "commit_index": self.commit_index, 
                 "last_applied": self.last_applied, 
                 "log_length": len(self.log) 
             }