from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

DEFAULT_BASE_PORT = 9999
DEFAULT_BATCH_SIZE = 4
DEFAULT_INTER_LAUNCH_DELAY = 3.0
DEFAULT_BATCH_SETTLE_DELAY = 10.0
DEFAULT_TIMEOUT = 120.0
DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_BRIGHTNESS_REFRESH_INTERVAL = 6.0


@dataclass(frozen=True)
class LauncherPaths:
    sandboxie_start: str
    steam_exe: str
    isaac_app_id: str
    sandbox_prefix: str
    cheat_engine_dir: Path
    cheat_engine_executables: tuple[str, ...]
    cheat_engine_processes: tuple[str, ...]

    @property
    def cheat_engine_autorun_file(self) -> Path:
        return self.cheat_engine_dir / "autorun" / "custom" / "isaac_speedhack_autorun.lua"


@dataclass(frozen=True)
class LauncherConfig:
    workers: int = 2
    base_port: int = DEFAULT_BASE_PORT
    batch_size: int = DEFAULT_BATCH_SIZE
    timeout: float = DEFAULT_TIMEOUT
    inter_launch_delay: float = DEFAULT_INTER_LAUNCH_DELAY
    batch_settle_delay: float = DEFAULT_BATCH_SETTLE_DELAY
    auto_start: bool = True
    ensure_ce: bool = True
    ce_reinstall_autorun: bool = False
    ce_speed: float = 10.0
    ce_scan_ms: int = 1000
    ce_startup_delay: float = 2.0
    host: str = "127.0.0.1"
    poll_interval: float = DEFAULT_POLL_INTERVAL
    brightness_refresh_interval: float = DEFAULT_BRIGHTNESS_REFRESH_INTERVAL

    def worker_ids(self) -> list[int]:
        return list(range(1, self.workers + 1))

    def port_for(self, worker_id: int) -> int:
        return self.base_port + (worker_id - 1)

    def sandbox_name(self, paths: LauncherPaths, worker_id: int) -> str:
        return f"{paths.sandbox_prefix}{worker_id}"


def default_paths() -> LauncherPaths:
    cheat_engine_dir = Path(os.getenv("CHEAT_ENGINE_DIR", r"C:\Program Files\Cheat Engine"))
    return LauncherPaths(
        sandboxie_start=os.getenv("SANDBOXIE_PATH", r"C:\Program Files\Sandboxie-Plus\Start.exe"),
        steam_exe=os.getenv("STEAM_PATH", r"C:\Program Files (x86)\Steam\steam.exe"),
        isaac_app_id=os.getenv("ISAAC_APP_ID", "250900"),
        sandbox_prefix="IsaacWorker",
        cheat_engine_dir=cheat_engine_dir,
        cheat_engine_executables=(
            "cheatengine-x86_64.exe",
            "cheatengine-x86_64-SSE4-AVX2.exe",
            "Cheat Engine.exe",
            "cheatengine-i386.exe",
        ),
        cheat_engine_processes=(
            "cheatengine-x86_64.exe",
            "cheatengine-x86_64-sse4-avx2.exe",
            "cheat engine.exe",
            "cheatengine-i386.exe",
        ),
    )


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
