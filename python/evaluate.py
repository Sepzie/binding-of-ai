import argparse
from pathlib import Path

import numpy as np

try:
    from sb3_contrib import MaskablePPO as PPO
    from sb3_contrib.common.maskable.utils import get_action_masks
except ImportError as exc:
    raise ImportError(
        "sb3-contrib is required for masked-policy evaluation. "
        "Install dependencies from python/requirements.txt."
    ) from exc

from checkpoint_manager import CheckpointManager
from config import load_config
from isaac_env import IsaacEnv
CHECKPOINT_ROOT = Path(__file__).resolve().parent.parent / "checkpoints"


def resolve_config_path(model: str, explicit_config: str | None) -> str | None:
    """Auto-detect config from checkpoint metadata if not explicitly provided."""
    if explicit_config is not None:
        return explicit_config

    meta = CheckpointManager.read_model_meta(CHECKPOINT_ROOT, model)
    config_path = meta.get("config_path")
    if config_path:
        resolved = CHECKPOINT_ROOT.parent / config_path
        if resolved.is_file():
            print(f"Auto-detected config: {config_path}")
            return str(resolved)
    return None


def evaluate(
    model_path: str,
    config_path: str | None = None,
    n_episodes: int = 20,
    meta: dict | None = None,
    use_wandb: bool = False,
):
    config = load_config(config_path)
    env = IsaacEnv(config)

    model = PPO.load(model_path)
    print(f"Loaded model from {model_path}")

    # W&B init
    wandb_run = None
    if use_wandb:
        import wandb

        train_run_id = (meta or {}).get("wandb_run_id")
        wandb_project = (meta or {}).get("wandb_project", "binding-of-ai")
        model_name = Path(model_path).stem
        run_name = f"eval-{train_run_id}-{model_name}" if train_run_id else f"eval-{model_name}"

        wandb_run = wandb.init(
            project=wandb_project,
            name=run_name,
            tags=["eval"] + ([f"train:{train_run_id}"] if train_run_id else []),
            config={
                "eval_episodes": n_episodes,
                "model_path": model_path,
                "config_path": config_path,
                "train_run_id": train_run_id,
            },
            job_type="eval",
        )

    episode_rewards = []
    episode_lengths = []
    wins = 0
    pickups = 0

    for ep in range(n_episodes):
        obs, info = env.reset()
        total_reward = 0.0
        steps = 0
        done = False

        while not done:
            action_masks = get_action_masks(env)
            action, _ = model.predict(obs, action_masks=action_masks, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            steps += 1
            done = terminated or truncated

        episode_rewards.append(total_reward)
        episode_lengths.append(steps)

        state = info.get("state")
        cleared = bool(state.room_cleared) if state is not None else False
        if cleared:
            wins += 1
        pickup = info.get("ep_reward_components", {}).get("pickup_collected", 0) > 0
        if pickup:
            pickups += 1

        print(f"Episode {ep + 1}: reward={total_reward:.1f}, steps={steps}, "
              f"cleared={cleared}")

        if wandb_run:
            wandb.log({
                "eval/episode_reward": total_reward,
                "eval/episode_length": steps,
                "eval/won": float(cleared),
                "eval/pickup": float(pickup),
            }, step=ep + 1)

    mean_reward = float(np.mean(episode_rewards))
    std_reward = float(np.std(episode_rewards))
    mean_length = float(np.mean(episode_lengths))
    win_rate = wins / n_episodes
    pickup_rate = pickups / n_episodes

    print(f"\n--- Results ({n_episodes} episodes) ---")
    print(f"Mean reward: {mean_reward:.1f} +/- {std_reward:.1f}")
    print(f"Mean length: {mean_length:.0f}")
    print(f"Win rate: {wins}/{n_episodes} ({100 * win_rate:.0f}%)")
    print(f"Pickup rate: {pickups}/{n_episodes} ({100 * pickup_rate:.0f}%)")

    if wandb_run:
        wandb.summary.update({
            "eval/mean_reward": mean_reward,
            "eval/std_reward": std_reward,
            "eval/mean_length": mean_length,
            "eval/win_rate": win_rate,
            "eval/pickup_rate": pickup_rate,
            "eval/n_episodes": n_episodes,
        })
        wandb.finish()
        print(f"Results logged to W&B: {wandb_run.url}")

    env.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate Isaac RL agent")
    parser.add_argument("model", type=str, help="Path to model .zip, or a W&B run ID suffix (e.g. ep7xefgq)")
    parser.add_argument("--config", type=str, default=None, help="Path to YAML config")
    parser.add_argument("--episodes", type=int, default=20, help="Number of evaluation episodes")
    parser.add_argument("--no-wandb", action="store_true", help="Disable W&B logging")
    args = parser.parse_args()
    model_path = CheckpointManager.resolve_model_path(CHECKPOINT_ROOT, args.model)
    config_path = resolve_config_path(args.model, args.config)
    meta = CheckpointManager.read_model_meta(CHECKPOINT_ROOT, args.model)
    print(f"Resolved model: {model_path}")
    evaluate(model_path, config_path, args.episodes, meta=meta, use_wandb=not args.no_wandb)
