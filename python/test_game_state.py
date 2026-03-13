import unittest

from game_state import GameState


class GameStateTests(unittest.TestCase):
    def test_from_dict_reads_pickups_collected(self):
        state = GameState.from_dict(
            {
                "episode_id": 3,
                "episode_tick": 17,
                "pickups_collected": 4,
                "terminal": True,
                "terminal_reason": "pickup_target_reached",
            }
        )

        self.assertEqual(state.episode_id, 3)
        self.assertEqual(state.episode_tick, 17)
        self.assertEqual(state.pickups_collected, 4)
        self.assertTrue(state.terminal)
        self.assertEqual(state.terminal_reason, "pickup_target_reached")


if __name__ == "__main__":
    unittest.main()
