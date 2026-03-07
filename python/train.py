import argparse
import logging
import signal
from pathlib import Path

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback
from stable_baselines3.common.monitor import Monitor

from config import load_config
from isaac_env import IsaacEnv
from network import IsaacFeatureExtractor


def train(config_path: str | None = None, resume: str | None = None):
    log = logging.getLogger("train")
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    config = load_config(config_path)

    isaac_env = IsaacEnv(config)

    # Configure the game settings before wrapping
    isaac_env._connect()
    isaac_env._send({
        "command": "configure",
        "settings": {
            "enemy_type": config.phase.enemy_type,
            "enemy_variant": config.phase.enemy_variant,
            "enemy_count": config.phase.enemy_count,
            "spawn_enemies": config.phase.spawn_enemies,
            "frame_skip": config.env.frame_skip,
        },
    })

    env = Monitor(isaac_env)

    checkpoint_dir = Path("../checkpoints")
    log_dir = Path("../logs")
    checkpoint_dir.mkdir(exist_ok=True)
    log_dir.mkdir(exist_ok=True)

    policy_kwargs = {
        "features_extractor_class": IsaacFeatureExtractor,
        "features_extractor_kwargs": {"features_dim": 256},
        "net_arch": {"pi": [128, 64], "vf": [128, 64]},
    }

    if resume:
        model = PPO.load(resume, env=env)
        log.info("Resumed from %s", resume)
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

    checkpoint_callback = CheckpointCallback(
        save_freq=config.train.save_interval,
        save_path=str(checkpoint_dir),
        name_prefix="isaac_rl",
    )

    # Graceful SIGINT: save checkpoint before exiting
    interrupted = False

    def _on_sigint(sig, frame):
        nonlocal interrupted
        if interrupted:
            log.warning("Second interrupt, forcing exit")
            raise SystemExit(1)
        interrupted = True
        log.info("Interrupt received, saving checkpoint...")
        model.save(str(checkpoint_dir / "interrupted_model"))
        log.info("Saved to %s", checkpoint_dir / "interrupted_model.zip")
        env.close()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _on_sigint)

    try:
        model.learn(
            total_timesteps=config.train.total_timesteps,
            callback=[checkpoint_callback],
            log_interval=config.train.log_interval,
        )
        model.save(str(checkpoint_dir / "final_model"))
        log.info("Training complete. Model saved to %s", checkpoint_dir / "final_model")
    except Exception:
        log.exception("Training crashed, saving emergency checkpoint...")
        model.save(str(checkpoint_dir / "crashed_model"))
        log.info("Saved to %s", checkpoint_dir / "crashed_model.zip")
        raise
    finally:
        env.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Isaac RL agent")
    parser.add_argument("--config", type=str, default=None, help="Path to YAML config")
    parser.add_argument("--resume", type=str, default=None, help="Path to checkpoint to resume from")
    args = parser.parse_args()
    train(args.config, args.resume)
