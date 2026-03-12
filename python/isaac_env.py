import json
import logging
import socket
import time
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from config import Config
from reward import RewardShaper

log = logging.getLogger("IsaacEnv")


class IsaacEnv(gym.Env):
    """Gymnasium environment wrapper for The Binding of Isaac via TCP.

    Protocol: Lua owns the game clock and episode lifecycle.
    - Lua streams observations with episode_id, terminal, terminal_reason
    - Lua restarts immediately on terminal, increments episode_id
    - Python sends actions (fire-and-forget), syncs on episode_id for reset
    """

    metadata = {"render_modes": []}

    def __init__(self, config: Config | None = None):
        super().__init__()
        self.config = config or Config()
        self.env_cfg = self.config.env
        self.reward_shaper = RewardShaper(self.config.reward)

        # Action space: MultiDiscrete([9, 5]) = 9 movement * 5 shooting
        self.action_space = spaces.MultiDiscrete([9, 5])

        # Observation space: Dict with grid (CNN input) and player (vector input)
        self.observation_space = spaces.Dict({
            "grid": spaces.Box(
                low=0.0,
                high=1.0,
                shape=(self.env_cfg.grid_channels, self.env_cfg.grid_height, self.env_cfg.grid_width),
                dtype=np.float32,
            ),
            "player": spaces.Box(
                low=-np.inf,
                high=np.inf,
                shape=(self.env_cfg.player_features,),
                dtype=np.float32,
            ),
        })

        self.sock = None
        self.sock_file = None
        self.step_count = 0
        self.last_state = None
        self._episode_num = 0
        self._last_episode_id = 0  # tracks Lua's episode_id

        # Throughput tracking
        self._total_steps = 0
        self._start_time = None
        self._throughput_interval = 1000

        # Episode tracking
        self._ep_reward = 0.0
        self._ep_kills = 0
        self._ep_damage_taken = 0
        self._ep_reward_components: dict[str, float] = {}
        self._last_terminal_reason = None

        # Speed diagnostics
        self._last_episode_tick = 0
        self._ep_frames_dropped = 0
        self._ep_step_latencies = []
        self._ep_receive_times = []  # wall-clock time of each received state

    # Reconnect settings
    MAX_RECONNECT_RETRIES = 5
    RECONNECT_BACKOFF_BASE = 1.0  # seconds, doubles each retry

    def _connect(self):
        if self.sock is not None:
            return
        last_err = None
        for attempt in range(self.MAX_RECONNECT_RETRIES + 1):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(self.env_cfg.action_timeout)
                self.sock.connect((self.env_cfg.host, self.env_cfg.port))
                self.sock_file = self.sock.makefile("r")
                log.info("Connected to %s:%d", self.env_cfg.host, self.env_cfg.port)
                return
            except (ConnectionError, OSError) as e:
                last_err = e
                self._disconnect()
                if attempt < self.MAX_RECONNECT_RETRIES:
                    delay = self.RECONNECT_BACKOFF_BASE * (2 ** attempt)
                    log.warning(
                        "Connect failed to %s:%d (%s), retry %d/%d in %.1fs...",
                        self.env_cfg.host, self.env_cfg.port, e,
                        attempt + 1, self.MAX_RECONNECT_RETRIES, delay,
                    )
                    time.sleep(delay)
        raise ConnectionError(
            f"Failed to connect to {self.env_cfg.host}:{self.env_cfg.port} "
            f"after {self.MAX_RECONNECT_RETRIES + 1} attempts: {last_err}"
        )

    def _disconnect(self):
        """Clean up socket state."""
        if self.sock_file:
            try:
                self.sock_file.close()
            except OSError:
                pass
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self.sock_file = None

    def _reconnect(self):
        """Disconnect and reconnect (retry logic is in _connect)."""
        self._disconnect()
        self._connect()

    def _send(self, data: dict):
        msg = json.dumps(data) + "\n"
        try:
            self.sock.sendall(msg.encode())
        except (ConnectionError, OSError) as e:
            # Don't reconnect on timeouts — let callers handle those
            if isinstance(e, (TimeoutError, socket.timeout)):
                raise
            log.warning("Send failed (%s), attempting reconnect", e)
            self._reconnect()
            # Re-send after reconnect
            self.sock.sendall(msg.encode())

    def _receive(self) -> dict:
        try:
            line = self.sock_file.readline()
            if not line:
                raise ConnectionError("Connection closed by game")
            return json.loads(line)
        except (ConnectionError, OSError) as e:
            # Don't reconnect on timeouts — let callers handle those
            if isinstance(e, (TimeoutError, socket.timeout)):
                raise
            log.warning("Receive failed (%s), attempting reconnect", e)
            self._reconnect()
            # After reconnect, read the next available state
            line = self.sock_file.readline()
            if not line:
                raise ConnectionError("Connection closed by game after reconnect")
            return json.loads(line)

    def _state_to_obs(self, state: dict) -> dict:
        grid = np.array(state["grid"], dtype=np.float32)
        if grid.shape != (self.env_cfg.grid_channels, self.env_cfg.grid_height, self.env_cfg.grid_width):
            grid = np.zeros(
                (self.env_cfg.grid_channels, self.env_cfg.grid_height, self.env_cfg.grid_width),
                dtype=np.float32,
            )

        p = state.get("player", {})
        player = np.array([
            p.get("hp_red", 0),
            p.get("hp_soul", 0),
            p.get("hp_black", 0),
            p.get("speed", 1.0),
            p.get("damage", 3.5),
            p.get("range", 6.5),
            p.get("fire_rate", 10),
            p.get("shot_speed", 1.0),
            p.get("luck", 0),
            p.get("num_bombs", 0),
            p.get("num_keys", 0),
            p.get("num_coins", 0),
            1.0 if p.get("has_active_item") else 0.0,
            p.get("active_charge", 0),
        ], dtype=np.float32)

        return {"grid": grid, "player": player}

    def _wait_for_new_episode(self, timeout=120.0):
        """Wait for first non-terminal observation of a new episode_id."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                state = self._receive()
                eid = state.get("episode_id", 0)
                if eid > self._last_episode_id and not state.get("terminal", False):
                    return state
            except (TimeoutError, OSError):
                continue
        raise ConnectionError(
            f"Timed out waiting for new episode (last_id={self._last_episode_id})"
        )

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._connect()

        # Log previous episode summary
        if self._episode_num > 0:
            reason = self._last_terminal_reason or "unknown"
            avg_latency = (
                sum(self._ep_step_latencies) / len(self._ep_step_latencies) * 1000
                if self._ep_step_latencies else 0.0
            )
            ticks_per_sec = 0.0
            if len(self._ep_receive_times) >= 2:
                duration = self._ep_receive_times[-1] - self._ep_receive_times[0]
                if duration > 0:
                    ticks_per_sec = (len(self._ep_receive_times) - 1) / duration
            log.info(
                "EP %d ended (%s) | steps=%d reward=%.1f kills=%d dmg_taken=%d "
                "frames_dropped=%d avg_latency=%.1fms ticks/s=%.1f",
                self._episode_num, reason, self.step_count,
                self._ep_reward, self._ep_kills, self._ep_damage_taken,
                self._ep_frames_dropped, avg_latency, ticks_per_sec,
            )

        self._episode_num += 1
        self.step_count = 0
        self._ep_reward = 0.0
        self._ep_kills = 0
        self._ep_damage_taken = 0
        self._ep_reward_components = {}
        self._last_terminal_reason = None
        self._last_episode_tick = 0
        self._ep_frames_dropped = 0
        self._ep_step_latencies = []
        self._ep_receive_times = []
        self.reward_shaper.reset()

        if self._last_episode_id == 0:
            # First episode in this Python process: force game back to active play
            # and request a fresh episode so stale paused state cannot leak across runs.
            self._send({"command": "resume"})
            self._send({"command": "reset"})
            log.debug("Initial reset sent, waiting for first episode...")

        # Wait for observation with a new episode_id (Lua auto-restarts)
        state = self._wait_for_new_episode()
        self._last_episode_id = state["episode_id"]
        self.last_state = state

        log.debug("EP %d started (game ep %d) | enemies=%d",
                  self._episode_num, self._last_episode_id,
                  state.get("enemy_count", 0))

        obs = self._state_to_obs(state)
        info = {"state": state, "reward_components": {}}
        return obs, info

    def step(self, action):
        self.step_count += 1
        self._total_steps += 1
        if self._start_time is None:
            self._start_time = time.monotonic()
        elif self._total_steps % self._throughput_interval == 0:
            elapsed = time.monotonic() - self._start_time
            sps = self._total_steps / elapsed
            log.info("%d steps, %.1f steps/sec", self._total_steps, sps)

        move_action = int(action[0])
        shoot_action = int(action[1])

        # Send action (fire-and-forget, Lua latches it)
        self._send({
            "command": "action",
            "action": {"move": move_action, "shoot": shoot_action},
        })

        # Receive next state from Lua's stream (measure wait time)
        t_before = time.monotonic()
        state = self._receive()
        t_after = time.monotonic()
        step_latency = t_after - t_before
        self._ep_step_latencies.append(step_latency)
        self._ep_receive_times.append(t_after)

        # Detect dropped frames via episode_tick gaps
        episode_tick = state.get("episode_tick", 0)
        if self._last_episode_tick > 0 and episode_tick > 0:
            expected = self._last_episode_tick + 1
            if episode_tick > expected:
                self._ep_frames_dropped += episode_tick - expected
        self._last_episode_tick = episode_tick

        # Compute reward
        reward = self.reward_shaper.compute(state)
        self._ep_reward += reward

        # Track episode stats
        rc = self.reward_shaper.reward_components
        for key, value in rc.items():
            self._ep_reward_components[key] = self._ep_reward_components.get(key, 0.0) + value
        if rc.get("kills", 0) > 0:
            self._ep_kills += int(rc["kills"] / self.config.reward.enemy_killed)
        if rc.get("damage_taken", 0) < 0:
            self._ep_damage_taken += 1

        # Terminal from Lua's detection
        terminated = state.get("terminal", False)
        terminal_reason = state.get("terminal_reason")

        # Gymnasium convention: timeout is truncation, not termination
        truncated = terminal_reason == "timeout"
        if truncated:
            terminated = False

        if terminated or truncated:
            self._last_terminal_reason = terminal_reason

        # Compute live ticks/sec from wall-clock receive times
        game_ticks_per_sec = 0.0
        if len(self._ep_receive_times) >= 2:
            duration = self._ep_receive_times[-1] - self._ep_receive_times[0]
            if duration > 0:
                game_ticks_per_sec = (len(self._ep_receive_times) - 1) / duration

        obs = self._state_to_obs(state)
        # Fraction of steps where state was already buffered (latency < 1ms)
        instant_ratio = 0.0
        avg_latency = step_latency
        if self._ep_step_latencies:
            instant_ratio = sum(1 for l in self._ep_step_latencies if l < 0.001) / len(self._ep_step_latencies)
            avg_latency = sum(self._ep_step_latencies) / len(self._ep_step_latencies)

        info = {
            "state": state,
            "reward_components": self.reward_shaper.reward_components.copy(),
            "ep_reward_components": self._ep_reward_components.copy(),
            "ep_kills": self._ep_kills,
            "ep_damage_taken": self._ep_damage_taken,
            "step_latency": step_latency,
            "avg_step_latency": avg_latency,
            "instant_ratio": instant_ratio,
            "frames_dropped": self._ep_frames_dropped,
            "game_ticks_per_sec": game_ticks_per_sec,
        }

        self.last_state = state
        return obs, reward, terminated, truncated, info

    def action_masks(self) -> np.ndarray:
        """Return flattened action mask for MultiDiscrete([9, 5])."""
        move_mask = np.ones(9, dtype=bool)

        if self.config.phase.mask_shoot:
            # Allow only "don't shoot" (0); mask shoot directions 1..4.
            shoot_mask = np.array([True, False, False, False, False], dtype=bool)
        else:
            shoot_mask = np.ones(5, dtype=bool)

        return np.concatenate((move_mask, shoot_mask))

    def pause_game(self):
        """Pause the game (used between rollout collection and PPO update)."""
        self._send({"command": "pause"})

    def resume_and_flush(self):
        """Resume the game and flush stale TCP data from the buffer."""
        self._send({"command": "resume"})
        flushed_bytes = 0
        self.sock.setblocking(False)
        try:
            while True:
                data = self.sock.recv(65536)
                if not data:
                    break
                flushed_bytes += len(data)
        except (BlockingIOError, OSError):
            pass
        self.sock.setblocking(True)
        self.sock.settimeout(self.env_cfg.action_timeout)
        self.sock_file = self.sock.makefile("r")
        return flushed_bytes

    def configure_game(self, settings: dict):
        """Send game configuration to the Lua mod."""
        self._connect()
        self._send({"command": "configure", "settings": settings})

    def close(self):
        # Best-effort cleanup: don't leave the game paused when training exits.
        if self.sock is not None:
            try:
                self._send({"command": "resume"})
            except (ConnectionError, OSError, TimeoutError, socket.timeout):
                pass
        self._disconnect()
