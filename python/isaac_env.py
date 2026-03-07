import json
import socket
import time
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from config import Config
from reward import RewardShaper


class IsaacEnv(gym.Env):
    """Gymnasium environment wrapper for The Binding of Isaac via TCP."""

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
        self._had_enemies = False

        # Throughput tracking
        self._total_steps = 0
        self._start_time = None
        self._throughput_interval = 1000  # log every N steps

    def _connect(self):
        if self.sock is not None:
            return
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.env_cfg.action_timeout)
        self.sock.connect((self.env_cfg.host, self.env_cfg.port))
        self.sock_file = self.sock.makefile("r")

    def _send(self, data: dict):
        msg = json.dumps(data) + "\n"
        self.sock.sendall(msg.encode())

    def _receive(self) -> dict:
        line = self.sock_file.readline()
        if not line:
            raise ConnectionError("Connection closed by game")
        return json.loads(line)

    def _state_to_obs(self, state: dict) -> dict:
        # Grid observation
        grid = np.array(state["grid"], dtype=np.float32)
        # Should be (channels, height, width)
        if grid.shape != (self.env_cfg.grid_channels, self.env_cfg.grid_height, self.env_cfg.grid_width):
            # Try to reshape if flat
            grid = np.zeros(
                (self.env_cfg.grid_channels, self.env_cfg.grid_height, self.env_cfg.grid_width),
                dtype=np.float32,
            )

        # Player state vector
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

    def _drain_and_receive(self, predicate, max_attempts=300):
        """Drain buffered states until we get one matching predicate."""
        for _ in range(max_attempts):
            state = self._receive()
            if predicate(state):
                return state
        raise ConnectionError("Timed out waiting for valid state after reset")

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._connect()
        self.step_count = 0
        self._had_enemies = False
        self.reward_shaper.reset()

        # Drain any buffered state from game
        state = self._receive()

        # Send reset command
        self._send({"command": "reset"})

        # Drain stale states until we get a valid post-reset state
        # (player alive, indicating the restart completed)
        state = self._drain_and_receive(
            lambda s: not s.get("player_dead", False)
        )
        self.last_state = state

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
            print(f"[IsaacEnv] {self._total_steps} steps, {sps:.1f} steps/sec")

        move_action = int(action[0])
        shoot_action = int(action[1])

        # Send action to game
        self._send({
            "command": "step",
            "action": {"move": move_action, "shoot": shoot_action},
        })

        # Receive next state
        state = self._receive()

        # Compute reward
        reward = self.reward_shaper.compute(state)

        # Track whether enemies have appeared
        if state.get("enemy_count", 0) > 0:
            self._had_enemies = True

        # Check termination: player died, or all enemies killed after they spawned
        terminated = state.get("player_dead", False)
        if not terminated and self._had_enemies and state.get("enemy_count", 0) == 0:
            terminated = True
        truncated = self.step_count >= self.env_cfg.max_episode_steps

        obs = self._state_to_obs(state)
        info = {
            "state": state,
            "reward_components": self.reward_shaper.reward_components.copy(),
        }

        self.last_state = state
        return obs, reward, terminated, truncated, info

    def close(self):
        if self.sock_file:
            self.sock_file.close()
        if self.sock:
            self.sock.close()
        self.sock = None
        self.sock_file = None
