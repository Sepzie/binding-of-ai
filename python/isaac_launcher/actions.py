from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import time

from win32_utils import VK_RETURN, send_key

from .config import LauncherPaths

log = logging.getLogger("isaac_launcher.actions")
START_SEQUENCE: tuple[tuple[int, float], ...] = tuple((VK_RETURN, 0.3) for _ in range(12))


def sandbox_name(paths: LauncherPaths, worker_id: int) -> str:
    return f"{paths.sandbox_prefix}{worker_id}"


def launch_worker(paths: LauncherPaths, worker_id: int, port: int) -> subprocess.Popen:
    """Launch Isaac inside a Sandboxie sandbox with the given port."""
    box = sandbox_name(paths, worker_id)
    cmd = [
        paths.sandboxie_start,
        f"/box:{box}",
        f"/env:ISAAC_RL_PORT={port}",
        f"/env:ISAAC_RL_INSTANCE={worker_id}",
        paths.steam_exe,
        "-offline",
        "-silent",
        "-applaunch",
        paths.isaac_app_id,
    ]
    log.info("Launching worker %d in sandbox %s on port %d", worker_id, box, port)
    return subprocess.Popen(cmd)


def terminate_worker(paths: LauncherPaths, worker_id: int) -> None:
    box = sandbox_name(paths, worker_id)
    cmd = [paths.sandboxie_start, f"/box:{box}", "/terminate"]
    log.info("Terminating sandbox %s", box)
    subprocess.run(cmd, capture_output=True)


def send_start_sequence(hwnd: int, title: str) -> None:
    """Send the configured start key sequence to a window."""
    log.info("Sending start keys to %s", title)
    for vk_code, delay in START_SEQUENCE:
        send_key(hwnd, vk_code)
        time.sleep(delay)


def _tasklist_running(image_name: str) -> bool:
    cmd = ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False
    output = (result.stdout or "").lower()
    if "no tasks are running" in output:
        return False
    return image_name.lower() in output


def is_cheat_engine_running(paths: LauncherPaths) -> bool:
    return any(_tasklist_running(name) for name in paths.cheat_engine_processes)


def find_cheat_engine_exe(paths: LauncherPaths) -> Path | None:
    for exe_name in paths.cheat_engine_executables:
        exe_path = paths.cheat_engine_dir / exe_name
        if exe_path.exists():
            return exe_path
    return None


def reinstall_ce_autorun(repo_root: Path, speed: float, scan_ms: int) -> bool:
    installer = repo_root / "scripts" / "install_ce_speedhack_watch.ps1"
    if not installer.exists():
        log.error("Autorun installer not found: %s", installer)
        return False

    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(installer),
        "-Action",
        "Install",
        "-Speed",
        str(speed),
        "-TargetProcess",
        "isaac-ng.exe",
        "-ScanIntervalMs",
        str(scan_ms),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("Failed to install CE autorun script.")
        if result.stdout:
            log.error("Installer stdout: %s", result.stdout.strip())
        if result.stderr:
            log.error("Installer stderr: %s", result.stderr.strip())
        return False
    if result.stdout:
        log.info("CE autorun install: %s", result.stdout.strip())
    return True


def ensure_cheat_engine_running(
    paths: LauncherPaths,
    repo_root: Path,
    reinstall_autorun: bool,
    ce_speed: float,
    ce_scan_ms: int,
    ce_startup_delay: float,
) -> bool:
    if reinstall_autorun:
        if not reinstall_ce_autorun(repo_root, ce_speed, ce_scan_ms):
            return False
    elif not paths.cheat_engine_autorun_file.exists():
        log.warning(
            "CE autorun script not found at %s. Use --ce-reinstall-autorun once to install it.",
            paths.cheat_engine_autorun_file,
        )

    if is_cheat_engine_running(paths):
        log.info("Cheat Engine already running.")
        return True

    ce_exe = find_cheat_engine_exe(paths)
    if ce_exe is None:
        log.error(
            "Cheat Engine executable not found in %s. Install CE or launch it manually before running workers.",
            paths.cheat_engine_dir,
        )
        return False

    log.info("Launching Cheat Engine: %s", ce_exe)
    subprocess.Popen([str(ce_exe)])
    if ce_startup_delay > 0:
        time.sleep(ce_startup_delay)
    return True
