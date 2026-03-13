import math
from collections.abc import Sequence

from config import RewardConfig
from game_state import GameState, PlayerState


class RewardShaper:
    """Computes reward from state diffs between consecutive ticks."""

    WALL_COLLISION_DISTANCE_THRESHOLD = 1.0
    WALL_COLLISION_AXIS_THRESHOLD = 0.5
    MOVE_DIRECTION_COMPONENTS = {
        1: (0, -1),
        2: (0, 1),
        3: (-1, 0),
        4: (1, 0),
        5: (-1, -1),
        6: (1, -1),
        7: (-1, 1),
        8: (1, 1),
    }

    def __init__(self, config: RewardConfig):
        self.config = config
        self.prev_state: GameState | None = None
        self.reward_components = {}
        self._nav_target: tuple[float, float] | None = None
        self._nav_reached = False

    def reset(self):
        self.prev_state = None
        self.reward_components = {}
        self._nav_target = None
        self._nav_reached = False

    def compute(self, state: GameState, action: Sequence[int] | None = None) -> float:
        reward = 0.0
        self.reward_components = {}

        if self.prev_state is None:
            self.prev_state = state
            return 0.0

        # Time penalty
        reward += self.config.time_penalty
        self.reward_components["time"] = self.config.time_penalty

        # Reward staying alive while enemies are still present.
        if state.enemy_count > 0 and not state.player_dead:
            reward += self.config.survival_bonus
            self.reward_components["survival_bonus"] = self.config.survival_bonus

        # Damage dealt (enemy HP decreased)
        damage_reward = self._compute_damage_dealt(state)
        reward += damage_reward
        self.reward_components["damage_dealt"] = damage_reward

        # Enemy killed (enemy count decreased)
        kill_reward = self._compute_kills(state)
        reward += kill_reward
        self.reward_components["kills"] = kill_reward

        # Damage taken (player HP decreased)
        damage_taken_reward = self._compute_damage_taken(state)
        reward += damage_taken_reward
        self.reward_components["damage_taken"] = damage_taken_reward

        # Pickup collected (currently measured via coin count increase)
        pickup_reward = self._compute_pickups(state)
        reward += pickup_reward
        self.reward_components["pickup_collected"] = pickup_reward

        wall_collision_reward = self._compute_wall_collision(state, action)
        reward += wall_collision_reward
        self.reward_components["wall_collision"] = wall_collision_reward

        # Navigation smoke-test objective (optional)
        nav_reward, nav_progress_reward, nav_reach_bonus = self._compute_nav_reward(state)
        reward += nav_reward
        if self._nav_target is not None:
            self.reward_components["nav_progress"] = nav_progress_reward
            self.reward_components["nav_reach_bonus"] = nav_reach_bonus

        # Room cleared
        if state.room_cleared and not self.prev_state.room_cleared:
            reward += self.config.room_cleared
            self.reward_components["room_cleared"] = self.config.room_cleared

        # Death
        if state.player_dead:
            reward += self.config.death
            self.reward_components["death"] = self.config.death

        self.prev_state = state
        return reward

    def _compute_damage_dealt(self, state: GameState) -> float:
        prev_enemies = {
            (e.type, e.variant, e.position[0], e.position[1]): e.hp
            for e in self.prev_state.enemies
        }
        reward = 0.0
        for enemy in state.enemies:
            key = (enemy.type, enemy.variant, enemy.position[0], enemy.position[1])
            # Try to match by proximity since positions change
            best_match_hp = None
            for pkey, php in prev_enemies.items():
                if pkey[0] == enemy.type and pkey[1] == enemy.variant:
                    if best_match_hp is None or php > best_match_hp:
                        best_match_hp = php
            if best_match_hp is not None and enemy.hp < best_match_hp:
                damage = best_match_hp - enemy.hp
                reward += damage * self.config.damage_dealt
        return reward

    def _compute_kills(self, state: GameState) -> float:
        prev_count = self.prev_state.enemy_count
        curr_count = state.enemy_count
        kills = max(0, prev_count - curr_count)
        return kills * self.config.enemy_killed

    def _compute_damage_taken(self, state: GameState) -> float:
        prev_hp = self._total_hp(self.prev_state.player)
        curr_hp = self._total_hp(state.player)
        if curr_hp < prev_hp:
            return self.config.damage_taken
        return 0.0

    def _compute_pickups(self, state: GameState) -> float:
        prev_coins = self.prev_state.player.num_coins
        curr_coins = state.player.num_coins
        collected = max(0, curr_coins - prev_coins)
        return collected * self.config.pickup_collected

    def _compute_wall_collision(
        self,
        state: GameState,
        action: Sequence[int] | None,
    ) -> float:
        if self.config.wall_collision_penalty == 0.0:
            return 0.0

        movement_action = self._movement_action(action)
        if movement_action == 0:
            return 0.0

        prev_pos = self._player_position(self.prev_state)
        curr_pos = self._player_position(state)
        if prev_pos is None or curr_pos is None:
            return 0.0

        dx = curr_pos[0] - prev_pos[0]
        dy = curr_pos[1] - prev_pos[1]
        if math.dist(prev_pos, curr_pos) < self.WALL_COLLISION_DISTANCE_THRESHOLD:
            return self.config.wall_collision_penalty

        move_components = self.MOVE_DIRECTION_COMPONENTS.get(movement_action)
        if not move_components:
            return 0.0

        for intended, actual in ((move_components[0], dx), (move_components[1], dy)):
            if intended != 0 and actual * intended < self.WALL_COLLISION_AXIS_THRESHOLD:
                return self.config.wall_collision_penalty

        return 0.0

    @staticmethod
    def _movement_action(action: Sequence[int] | None) -> int:
        if action is None:
            return 0

        try:
            if len(action) == 0:
                return 0
        except TypeError:
            return 0

        try:
            return int(action[0])
        except (IndexError, TypeError, ValueError):
            return 0

    def _total_hp(self, player: PlayerState) -> float:
        return player.total_hp

    def _compute_nav_reward(self, state: GameState) -> tuple[float, float, float]:
        nav_enabled = (
            self.config.nav_progress_scale != 0.0
            or self.config.nav_reach_bonus != 0.0
        )
        if not nav_enabled:
            return 0.0, 0.0, 0.0

        if self._nav_target is None:
            self._nav_target = self._resolve_nav_target(state)
        if self._nav_target is None:
            return 0.0, 0.0, 0.0

        prev_pos = self._player_position(self.prev_state)
        curr_pos = self._player_position(state)
        if prev_pos is None or curr_pos is None:
            return 0.0, 0.0, 0.0

        prev_dist = math.dist(prev_pos, self._nav_target)
        curr_dist = math.dist(curr_pos, self._nav_target)

        nav_progress_reward = (prev_dist - curr_dist) * self.config.nav_progress_scale

        nav_reach_bonus = 0.0
        if (
            not self._nav_reached
            and curr_dist <= self.config.nav_reach_radius
        ):
            nav_reach_bonus = self.config.nav_reach_bonus
            self._nav_reached = True

        return nav_progress_reward + nav_reach_bonus, nav_progress_reward, nav_reach_bonus

    def _resolve_nav_target(self, state: GameState) -> tuple[float, float] | None:
        if self.config.nav_target_x is not None and self.config.nav_target_y is not None:
            return float(self.config.nav_target_x), float(self.config.nav_target_y)

        player_pos = self._player_position(state)
        if player_pos is None:
            return None

        return (
            player_pos[0] + self.config.nav_target_dx,
            player_pos[1] + self.config.nav_target_dy,
        )

    @staticmethod
    def _player_position(state: GameState | None) -> tuple[float, float] | None:
        if not state:
            return None
        return state.player.position
