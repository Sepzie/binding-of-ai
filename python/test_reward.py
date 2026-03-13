import os
import tempfile
import textwrap
import unittest

import numpy as np

from config import load_config, RewardConfig
from game_state import GameState, PlayerState
from reward import RewardShaper


def make_state(position: tuple[float, float]) -> GameState:
    return GameState(player=PlayerState(position=position))


class RewardShaperWallCollisionTests(unittest.TestCase):
    def make_shaper(self) -> RewardShaper:
        return RewardShaper(
            RewardConfig(
                damage_dealt=0.0,
                enemy_killed=0.0,
                damage_taken=0.0,
                room_cleared=0.0,
                pickup_collected=0.0,
                wall_collision_penalty=-0.5,
                death=0.0,
                time_penalty=0.0,
            )
        )

    def test_applies_wall_collision_penalty_when_moving_but_stuck(self):
        shaper = self.make_shaper()

        shaper.compute(make_state((100.0, 100.0)))
        reward = shaper.compute(make_state((100.0, 100.0)), action=(4, 0))

        self.assertEqual(reward, -0.5)
        self.assertEqual(shaper.reward_components["wall_collision"], -0.5)

    def test_skips_wall_collision_penalty_for_no_op_movement(self):
        shaper = self.make_shaper()

        shaper.compute(make_state((100.0, 100.0)))
        reward = shaper.compute(make_state((100.0, 100.0)), action=(0, 4))

        self.assertEqual(reward, 0.0)
        self.assertEqual(shaper.reward_components["wall_collision"], 0.0)

    def test_skips_wall_collision_penalty_when_player_moves(self):
        shaper = self.make_shaper()

        shaper.compute(make_state((100.0, 100.0)))
        reward = shaper.compute(make_state((102.0, 100.0)), action=(4, 0))

        self.assertEqual(reward, 0.0)
        self.assertEqual(shaper.reward_components["wall_collision"], 0.0)

    def test_applies_wall_collision_penalty_when_diagonal_move_slides_on_one_axis(self):
        shaper = self.make_shaper()

        shaper.compute(make_state((100.0, 100.0)))
        reward = shaper.compute(make_state((102.0, 100.1)), action=(6, 0))

        self.assertEqual(reward, -0.5)
        self.assertEqual(shaper.reward_components["wall_collision"], -0.5)

    def test_skips_wall_collision_penalty_when_diagonal_move_progresses_on_both_axes(self):
        shaper = self.make_shaper()

        shaper.compute(make_state((100.0, 100.0)))
        reward = shaper.compute(make_state((101.0, 99.0)), action=(6, 0))

        self.assertEqual(reward, 0.0)
        self.assertEqual(shaper.reward_components["wall_collision"], 0.0)

    def test_accepts_numpy_action_arrays_from_sb3(self):
        shaper = self.make_shaper()

        shaper.compute(make_state((100.0, 100.0)))
        reward = shaper.compute(make_state((102.0, 100.1)), action=np.array([6, 0]))

        self.assertEqual(reward, -0.5)
        self.assertEqual(shaper.reward_components["wall_collision"], -0.5)


class ConfigObstacleWiringTests(unittest.TestCase):
    def test_load_config_reads_obstacle_and_wall_collision_fields(self):
        config_text = textwrap.dedent(
            """
            reward:
              wall_collision_penalty: -0.5
            phase:
              spawn_obstacles: true
              obstacle_count: 3
              obstacle_type: 4
              obstacle_min_spacing: 2
            """
        )
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
            handle.write(config_text)
            path = handle.name

        try:
            config = load_config(path)
        finally:
            os.unlink(path)

        self.assertEqual(config.reward.wall_collision_penalty, -0.5)
        self.assertTrue(config.phase.spawn_obstacles)
        self.assertEqual(config.phase.obstacle_count, 3)
        self.assertEqual(config.phase.obstacle_type, 4)
        self.assertEqual(config.phase.obstacle_min_spacing, 2)


if __name__ == "__main__":
    unittest.main()
