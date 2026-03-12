import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class EnvConfig:
    host: str = "127.0.0.1"
    port: int = 9999
    grid_width: int = 13
    grid_height: int = 7
    grid_channels: int = 8
    include_continuous_position_features: bool = False
    player_features: int = 14
    frame_skip: int = 1
    max_episode_steps: int = 3000
    action_timeout: float = 5.0
    n_workers: int = 1
    base_port: int = 9999

    def __post_init__(self):
        self.sync_player_features()

    def sync_player_features(self):
        self.player_features = 22 if self.include_continuous_position_features else 14


@dataclass
class RewardConfig:
    damage_dealt: float = 1.0
    enemy_killed: float = 5.0
    damage_taken: float = -10.0
    room_cleared: float = 20.0
    pickup_collected: float = 2.0
    death: float = -50.0
    time_penalty: float = -0.1
    survival_bonus: float = 0.0
    floor_cleared: float = 100.0
    nav_progress_scale: float = 0.0
    nav_reach_bonus: float = 0.0
    nav_reach_radius: float = 20.0
    nav_target_x: float | None = None
    nav_target_y: float | None = None
    nav_target_dx: float = 0.0
    nav_target_dy: float = 0.0


@dataclass
class TrainConfig:
    algorithm: str = "PPO"
    learning_rate: float = 3e-4
    n_steps: int = 2048
    batch_size: int = 64
    n_epochs: int = 10
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_range: float = 0.2
    target_kl: float | None = None
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    total_timesteps: int = 1_000_000
    log_interval: int = 10
    save_interval: int = 50_000
    eval_episodes: int = 20


@dataclass
class PhaseConfig:
    enemy_type: int = 10
    enemy_variant: int = 0
    enemy_count: int = 1
    enemy_collision_damage: float | None = None
    spawn_pickup_penny: bool = False
    pickup_random_position: bool = False
    pickup_offset_x: float = 180.0
    pickup_offset_y: float = 0.0
    pickup_radius_min: float = 120.0
    pickup_radius_max: float = 200.0
    terminal_on_pickup: bool = False
    terminal_pickup_count: int = 0
    respawn_pickup: bool = False
    spawn_enemies: bool = True
    random_spawn_positions: bool = False
    spawn_radius_min: float = 80.0
    spawn_radius_max: float = 160.0
    disable_shooting: bool = False
    mask_shoot: bool = False


@dataclass
class WandbConfig:
    enabled: bool = False
    project: str = "binding-of-ai"
    entity: Optional[str] = None
    run_name: Optional[str] = None
    tags: list = field(default_factory=list)


@dataclass
class Config:
    env: EnvConfig = field(default_factory=EnvConfig)
    reward: RewardConfig = field(default_factory=RewardConfig)
    train: TrainConfig = field(default_factory=TrainConfig)
    phase: PhaseConfig = field(default_factory=PhaseConfig)
    wandb: WandbConfig = field(default_factory=WandbConfig)

    def to_game_settings(self) -> dict:
        """Build the settings dict sent to the Lua mod's configure command."""
        return {
            "enemy_type": self.phase.enemy_type,
            "enemy_variant": self.phase.enemy_variant,
            "enemy_count": self.phase.enemy_count,
            "enemy_collision_damage": self.phase.enemy_collision_damage,
            "spawn_pickup_penny": self.phase.spawn_pickup_penny,
            "pickup_random_position": self.phase.pickup_random_position,
            "pickup_offset_x": self.phase.pickup_offset_x,
            "pickup_offset_y": self.phase.pickup_offset_y,
            "pickup_radius_min": self.phase.pickup_radius_min,
            "pickup_radius_max": self.phase.pickup_radius_max,
            "terminal_on_pickup": self.phase.terminal_on_pickup,
            "terminal_pickup_count": self.phase.terminal_pickup_count,
            "respawn_pickup": self.phase.respawn_pickup,
            "spawn_enemies": self.phase.spawn_enemies,
            "random_spawn_positions": self.phase.random_spawn_positions,
            "spawn_radius_min": self.phase.spawn_radius_min,
            "spawn_radius_max": self.phase.spawn_radius_max,
            "disable_shooting": self.phase.disable_shooting,
            "frame_skip": self.env.frame_skip,
            "max_episode_ticks": self.env.max_episode_steps,
        }


def load_config(path: str | None = None) -> Config:
    """Load config from YAML file, falling back to defaults."""
    config = Config()
    if path is None:
        config.env.sync_player_features()
        return config

    with open(path) as f:
        data = yaml.safe_load(f)

    if not data:
        config.env.sync_player_features()
        return config

    for section_name, section_cls in [
        ("env", EnvConfig),
        ("reward", RewardConfig),
        ("train", TrainConfig),
        ("phase", PhaseConfig),
        ("wandb", WandbConfig),
    ]:
        if section_name in data:
            section = getattr(config, section_name)
            for key, value in data[section_name].items():
                if hasattr(section, key):
                    setattr(section, key, value)

    env_data = data.get("env", {})
    if isinstance(env_data, dict):
        has_include_flag = "include_continuous_position_features" in env_data
        has_player_features = "player_features" in env_data
        if not has_include_flag and has_player_features:
            pf = int(env_data["player_features"])
            if pf == 14:
                config.env.include_continuous_position_features = False
            elif pf == 22:
                config.env.include_continuous_position_features = True
            else:
                raise ValueError(
                    f"Unsupported env.player_features={pf}. Expected 14 or 22."
                )
        elif has_include_flag and has_player_features:
            expected = 22 if bool(env_data["include_continuous_position_features"]) else 14
            pf = int(env_data["player_features"])
            if pf != expected:
                raise ValueError(
                    "Config mismatch: env.player_features conflicts with "
                    "env.include_continuous_position_features."
                )

    config.env.sync_player_features()

    return config
