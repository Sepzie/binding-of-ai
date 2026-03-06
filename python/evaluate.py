import argparse
import numpy as np

from stable_baselines3 import PPO

from config import load_config
from isaac_env import IsaacEnv


def evaluate(model_path: str, config_path: str | None = None, n_episodes: int = 20):
    config = load_config(config_path)
    env = IsaacEnv(config)

    model = PPO.load(model_path)
    print(f"Loaded model from {model_path}")

    episode_rewards = []
    episode_lengths = []
    wins = 0

    for ep in range(n_episodes):
        obs, info = env.reset()
        total_reward = 0.0
        steps = 0
        done = False

        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            steps += 1
            done = terminated or truncated

        episode_rewards.append(total_reward)
        episode_lengths.append(steps)

        state = info.get("state", {})
        if state.get("room_cleared"):
            wins += 1

        print(f"Episode {ep + 1}: reward={total_reward:.1f}, steps={steps}, "
              f"cleared={state.get('room_cleared', False)}")

    print(f"\n--- Results ({n_episodes} episodes) ---")
    print(f"Mean reward: {np.mean(episode_rewards):.1f} +/- {np.std(episode_rewards):.1f}")
    print(f"Mean length: {np.mean(episode_lengths):.0f}")
    print(f"Win rate: {wins}/{n_episodes} ({100 * wins / n_episodes:.0f}%)")

    env.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate Isaac RL agent")
    parser.add_argument("model", type=str, help="Path to trained model")
    parser.add_argument("--config", type=str, default=None, help="Path to YAML config")
    parser.add_argument("--episodes", type=int, default=20, help="Number of evaluation episodes")
    args = parser.parse_args()
    evaluate(args.model, args.config, args.episodes)
