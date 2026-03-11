import argparse
import logging
import signal
from dataclasses import asdict, replace
from pathlib import Path

try:
    from sb3_contrib import MaskablePPO as PPO
except ImportError as exc:
    raise ImportError(
        "sb3-contrib is required for action masking. "
        "Install dependencies from python/requirements.txt."
    ) from exc
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv

from checkpoint_manager import CheckpointManager
from config import load_config
from isaac_env import IsaacEnv
from network import IsaacFeatureExtractor
from utils import (
    get_checkpoint_dir,
    get_log_dir,
    validate_ppo_checkpoint,
)


def resolve_resume_path(
    resume: str | None,
    checkpoint_dir: Path,
    config_path: str | None,
    env,
) -> str | None:
    """Resolve special resume modes to an actual checkpoint path.

    Modes:
        latest              — most recent checkpoint for the same config
        latest-any          — most recent checkpoint across all configs
        latest-compatible   — newest checkpoint (same config) that loads successfully
        run:<wandb_id>      — latest checkpoint from a specific W&B run
        <path>              — explicit path (absolute, relative, or filename in checkpoint_dir)
    """
    if resume is None:
        return None

    if resume.startswith("run:"):
        run_id = resume[4:]
        checkpoint = CheckpointManager.find_latest_for_run(checkpoint_dir, run_id)
        if checkpoint is None:
            raise FileNotFoundError(
                f"No checkpoints found for run '{run_id}' in {checkpoint_dir}"
            )
        return str(checkpoint)

    if resume == "latest":
        checkpoint = CheckpointManager.find_latest_for_config(checkpoint_dir, config_path)
        if checkpoint is None:
            raise FileNotFoundError(
                f"No checkpoints found for config '{Path(config_path).stem}' in {checkpoint_dir}"
            )
        return str(checkpoint)

    if resume == "latest-any":
        checkpoint = CheckpointManager.find_latest(checkpoint_dir)
        if checkpoint is None:
            raise FileNotFoundError(f"No checkpoints found in {checkpoint_dir}")
        return str(checkpoint)

    if resume == "latest-compatible":
        checkpoint = CheckpointManager.find_latest_compatible(
            checkpoint_dir,
            config_path,
            validator=lambda candidate: validate_ppo_checkpoint(candidate, env),
        )
        if checkpoint is None:
            raise FileNotFoundError(
                f"No compatible checkpoints found in {checkpoint_dir}"
            )
        return str(checkpoint)

    resume_path = Path(resume).expanduser()
    if resume_path.is_absolute():
        return str(resume_path)

    if resume_path.exists():
        return str(resume_path.resolve())

    checkpoint_candidate = checkpoint_dir / resume_path
    if checkpoint_candidate.exists():
        return str(checkpoint_candidate.resolve())

    return str(resume_path.resolve())


class ManagedCheckpointCallback(BaseCallback):
    """Save periodic checkpoints via CheckpointManager."""

    def __init__(self, manager: CheckpointManager, save_freq: int, verbose=0):
        super().__init__(verbose)
        self.manager = manager
        self.save_freq = save_freq

    def _on_step(self) -> bool:
        if self.num_timesteps % self.save_freq == 0:
            name = f"step_{self.num_timesteps:07d}"
            self.manager.save(self.model, name, self.num_timesteps, "periodic")
        return True


class GamePauseCallback(BaseCallback):
    """Pause the game during PPO training to prevent stale state buffering.

    Works with both single IsaacEnv and vectorized (SubprocVecEnv/DummyVecEnv) envs.
    """

    def __init__(self, env, verbose=0):
        super().__init__(verbose)
        self.env = env
        self._is_vec = hasattr(env, "env_method")

    def _on_rollout_end(self) -> None:
        if self._is_vec:
            self.env.env_method("pause_game")
        else:
            self.env.unwrapped.pause_game()

    def _on_rollout_start(self) -> None:
        if self._is_vec:
            results = self.env.env_method("resume_and_flush")
            total_flushed = sum(r for r in results if r)
        else:
            total_flushed = self.env.unwrapped.resume_and_flush()
        if total_flushed > 0:
            log = logging.getLogger("train")
            log.info("Flushed %d stale bytes from TCP buffer(s) at rollout start", total_flushed)

    def _on_step(self) -> bool:
        return True


class IsaacMetricsCallback(BaseCallback):
    """Log Isaac-specific episode metrics to wandb and console."""

    def __init__(self, use_wandb=False, verbose=0):
        super().__init__(verbose)
        self.use_wandb = use_wandb
        self._ep_count = 0

    def _on_step(self) -> bool:
        for info in self.locals.get("infos", []):
            if "episode" not in info:
                continue
            self._ep_count += 1

            state = info.get("state", {})
            ep_reward = info["episode"]["r"]
            ep_length = info["episode"]["l"]
            reason = state.get("terminal_reason", "unknown")
            kills = info.get("ep_kills", 0)
            dmg = info.get("ep_damage_taken", 0)
            tps = info.get("game_ticks_per_sec", 0)

            # Console summary (visible in main process)
            log = logging.getLogger("train")
            log.info(
                "EP %d (%s) | steps=%d reward=%.1f kills=%d dmg=%d ticks/s=%.1f [t=%d]",
                self._ep_count, reason, ep_length, ep_reward, kills, dmg, tps,
                self.num_timesteps,
            )

            if not self.use_wandb:
                continue
            import wandb

            # Gameplay metrics
            metrics = {
                "episode/reward": ep_reward,
                "episode/length": ep_length,
                "episode/won": float(reason == "room_cleared"),
                "episode/kills": kills,
                "episode/damage_taken": dmg,
            }

            # Cumulative reward component breakdown
            for component, value in info.get("ep_reward_components", {}).items():
                metrics[f"reward/{component}"] = value

            # Performance metrics
            if "frames_dropped" in info:
                metrics["perf/frames_dropped"] = info["frames_dropped"]
            if "avg_step_latency" in info:
                metrics["perf/avg_step_latency_ms"] = info["avg_step_latency"] * 1000
            if "instant_ratio" in info:
                metrics["perf/instant_ratio"] = info["instant_ratio"]
            if tps > 0:
                metrics["perf/game_ticks_per_sec"] = tps

            wandb.log(metrics, step=self.num_timesteps)
        return True


def _build_game_settings(config):
    """Build the settings dict sent to the Lua mod's configure command."""
    return {
        "enemy_type": config.phase.enemy_type,
        "enemy_variant": config.phase.enemy_variant,
        "enemy_count": config.phase.enemy_count,
        "enemy_collision_damage": config.phase.enemy_collision_damage,
        "spawn_pickup_penny": config.phase.spawn_pickup_penny,
        "pickup_random_position": config.phase.pickup_random_position,
        "pickup_offset_x": config.phase.pickup_offset_x,
        "pickup_offset_y": config.phase.pickup_offset_y,
        "pickup_radius_min": config.phase.pickup_radius_min,
        "pickup_radius_max": config.phase.pickup_radius_max,
        "terminal_on_pickup": config.phase.terminal_on_pickup,
        "spawn_enemies": config.phase.spawn_enemies,
        "random_spawn_positions": config.phase.random_spawn_positions,
        "spawn_radius_min": config.phase.spawn_radius_min,
        "spawn_radius_max": config.phase.spawn_radius_max,
        "disable_shooting": config.phase.disable_shooting,
        "frame_skip": config.env.frame_skip,
        "max_episode_ticks": config.env.max_episode_steps,
    }


def _make_env(config, port, game_settings):
    """Factory that creates a single IsaacEnv with the given port."""
    def _init():
        worker_config = replace(config, env=replace(config.env, port=port))
        env = IsaacEnv(worker_config)
        env.configure_game(game_settings)
        env.start_run()
        return Monitor(env)
    return _init


def train(config_path: str | None = None, resume: str | None = None):
    log = logging.getLogger("train")
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    # Silence noisy third-party loggers
    for noisy in ("urllib3", "git", "git.cmd", "git.util", "asyncio", "wandb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    config = load_config(config_path)
    n_workers = config.env.n_workers
    base_port = config.env.base_port
    game_settings = _build_game_settings(config)

    if n_workers > 1:
        log.info("Starting vectorized training with %d workers (ports %d-%d)",
                 n_workers, base_port, base_port + n_workers - 1)
        env_fns = [_make_env(config, base_port + i, game_settings) for i in range(n_workers)]
        env = SubprocVecEnv(env_fns)
    else:
        isaac_env = IsaacEnv(config)
        isaac_env.configure_game(game_settings)
        isaac_env.start_run()
        env = Monitor(isaac_env)

    checkpoint_dir = get_checkpoint_dir()
    log_dir = get_log_dir()
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Wandb init
    use_wandb = config.wandb.enabled
    wandb_run = None
    if use_wandb:
        import wandb
        wandb_run = wandb.init(
            project=config.wandb.project,
            entity=config.wandb.entity,
            name=config.wandb.run_name,
            tags=config.wandb.tags,
            config=asdict(config),
        )

    # Checkpoint manager — per-run folders, metadata, W&B artifacts
    ckpt_manager = CheckpointManager(
        base_dir=checkpoint_dir,
        config_path=config_path,
        config=config,
        wandb_run=wandb_run,
    )

    policy_kwargs = {
        "features_extractor_class": IsaacFeatureExtractor,
        "features_extractor_kwargs": {"features_dim": 256},
        "net_arch": {"pi": [128, 64], "vf": [128, 64]},
    }

    resume_path = resolve_resume_path(resume, checkpoint_dir, config_path, env)
    if resume_path:
        model = PPO.load(resume_path, env=env)
        log.info("Resumed from %s", resume_path)
    else:
        model = PPO(
            "MultiInputPolicy",
            env,
            learning_rate=config.train.learning_rate,
            n_steps=config.train.n_steps,
            batch_size=config.train.batch_size,
            n_epochs=config.train.n_epochs,
            gamma=config.train.gamma,
            gae_lambda=config.train.gae_lambda,
            clip_range=config.train.clip_range,
            ent_coef=config.train.ent_coef,
            vf_coef=config.train.vf_coef,
            max_grad_norm=config.train.max_grad_norm,
            policy_kwargs=policy_kwargs,
            verbose=1,
            tensorboard_log=str(log_dir),
        )

    checkpoint_callback = ManagedCheckpointCallback(
        manager=ckpt_manager,
        save_freq=config.train.save_interval,
    )

    callbacks = [
        checkpoint_callback,
        GamePauseCallback(env),
        IsaacMetricsCallback(use_wandb=use_wandb),
    ]

    # Graceful SIGINT: save checkpoint before exiting
    interrupted = False
    interrupt_checkpoint_path: Path | None = None

    def _save_interrupt_checkpoint() -> Path:
        nonlocal interrupt_checkpoint_path
        if interrupt_checkpoint_path is None:
            step = model.num_timesteps
            interrupt_checkpoint_path = ckpt_manager.save(
                model, "interrupted_model", step, "interrupted"
            )
        return interrupt_checkpoint_path

    def _on_sigint(_sig, _frame):
        nonlocal interrupted
        if interrupted:
            log.warning("Second interrupt, forcing exit")
            raise SystemExit(1)
        interrupted = True
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _on_sigint)

    try:
        model.learn(
            total_timesteps=config.train.total_timesteps,
            callback=callbacks,
            log_interval=config.train.log_interval,
        )
        step = model.num_timesteps
        checkpoint_path = ckpt_manager.save(model, "final_model", step, "final")
        log.info("Training complete. Model saved to %s", checkpoint_path)
    except KeyboardInterrupt:
        log.info("Interrupt received, saving checkpoint...")
        checkpoint_path = _save_interrupt_checkpoint()
        log.info("Saved to %s", checkpoint_path)
        log.info("Training interrupted. Exiting cleanly.")
    except Exception:
        if interrupted:
            checkpoint_path = _save_interrupt_checkpoint()
            log.warning(
                "Interrupted during shutdown. Preserving interrupt checkpoint at %s",
                checkpoint_path,
            )
            return
        log.exception("Training crashed, saving emergency checkpoint...")
        step = model.num_timesteps
        checkpoint_path = ckpt_manager.save(model, "crashed_model", step, "crashed")
        log.info("Saved to %s", checkpoint_path)
        raise
    finally:
        env.close()
        if use_wandb:
            import wandb
            wandb.finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Isaac RL agent")
    parser.add_argument("--config", type=str, default=None, help="Path to YAML config")
    parser.add_argument(
        "--resume",
        type=str,
        default=None,
        help="Checkpoint path, run:<wandb_id>, or one of: latest, latest-any, latest-compatible",
    )
    args = parser.parse_args()
    train(args.config, args.resume)
