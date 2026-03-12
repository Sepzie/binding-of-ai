"""Launcher for multi-instance Isaac RL training via Sandboxie-Plus.

Starts N Isaac game instances in separate Sandboxie sandboxes, each with a
unique TCP port. Auto-starts runs via keypress simulation once the game
windows are detected as loaded (pixel brightness check).

Usage:
    python launcher.py --workers 2
    python launcher.py --workers 3 --base-port 9999
    python launcher.py --terminate  # kill all workers
    python launcher.py --no-auto-start  # skip keypress simulation
"""

import argparse
import ctypes
import ctypes.wintypes
import logging
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Optional

from PIL import Image

log = logging.getLogger("launcher")

SANDBOXIE_START = r"C:\Program Files\Sandboxie-Plus\Start.exe"
STEAM_EXE = r"C:\Program Files (x86)\Steam\steam.exe"
ISAAC_APP_ID = "250900"
SANDBOX_PREFIX = "IsaacWorker"
DEFAULT_BASE_PORT = 9999
CHEAT_ENGINE_DIR = r"C:\Program Files\Cheat Engine"
CHEAT_ENGINE_EXE_CANDIDATES = [
    "cheatengine-x86_64.exe",
    "cheatengine-x86_64-SSE4-AVX2.exe",
    "Cheat Engine.exe",
    "cheatengine-i386.exe",
]
CHEAT_ENGINE_PROCESS_CANDIDATES = [
    "cheatengine-x86_64.exe",
    "cheatengine-x86_64-sse4-avx2.exe",
    "cheat engine.exe",
    "cheatengine-i386.exe",
]
CHEAT_ENGINE_AUTORUN_FILE = Path(
    CHEAT_ENGINE_DIR, "autorun", "custom", "isaac_speedhack_autorun.lua"
)

# Windows API
user32 = ctypes.windll.user32
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_RETURN = 0x0D
VK_RIGHT = 0x27
# Scan codes for lParam
SC_ENTER = 0x1C
SC_RIGHT = 0x4D

# Map VK to scan code for PostMessage lParam
_VK_TO_SC = {VK_RETURN: SC_ENTER, VK_RIGHT: SC_RIGHT}
_EXTENDED_KEYS = {VK_RIGHT}  # Arrow keys need extended bit (bit 24)


# ---------- Window / input helpers ----------

def _send_key(hwnd, vk_code):
    """Send a single keypress via PostMessage (works for Isaac in Sandboxie)."""
    sc = _VK_TO_SC.get(vk_code, 0)
    extended = (1 << 24) if vk_code in _EXTENDED_KEYS else 0
    lparam_down = extended | (sc << 16) | 1
    lparam_up = extended | (sc << 16) | 1 | (1 << 30) | (1 << 31)
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk_code, lparam_down)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_KEYUP, vk_code, lparam_up)


def find_isaac_windows():
    """Return list of (hwnd, title) for visible Isaac windows."""
    windows = []

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if "isaac" in title.lower() and "steam" not in title.lower():
                    windows.append((hwnd, title))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return windows


def get_pid_from_hwnd(hwnd) -> int:
    """Get the process ID that owns the given window handle."""
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_window_rect(hwnd):
    """Get window bounding box as (left, top, right, bottom)."""
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def window_brightness(hwnd) -> float:
    """Capture the window via PrintWindow and return average pixel brightness.

    Uses PrintWindow instead of ImageGrab so it works even when the window
    is behind other windows or partially off-screen.
    """
    rect = get_window_rect(hwnd)
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    if w < 10 or h < 10:
        return 0.0
    try:
        import win32gui
        import win32ui
        import win32con
        # Create device contexts and bitmap
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bitmap)
        # PW_RENDERFULLCONTENT = 2 captures even DX windows on some systems
        ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
        # Convert to PIL Image
        bmpinfo = bitmap.GetInfo()
        bmpstr = bitmap.GetBitmapBits(True)
        img = Image.frombuffer("RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                               bmpstr, "raw", "BGRX", 0, 1)
        # Cleanup
        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        # Sample center region (avoid window chrome)
        iw, ih = img.size
        crop = img.crop((iw // 4, ih // 4, 3 * iw // 4, 3 * ih // 4))
        pixels = list(crop.getdata())
        if not pixels:
            return 0.0
        avg = sum(sum(p[:3]) / 3 for p in pixels) / len(pixels)
        return avg
    except Exception as e:
        log.debug("window_brightness failed: %s", e)
        return 0.0


def wait_for_window_loaded(hwnd, title, timeout=120.0) -> bool:
    """Wait until the window shows the title screen (not black, not white).

    Loading sequence: black (0) -> white splash (255) -> title screen (50-220).
    Returns False quickly if brightness is unreadable (5 consecutive zeros).
    """
    deadline = time.monotonic() + timeout
    zero_count = 0
    while time.monotonic() < deadline:
        brightness = window_brightness(hwnd)
        log.debug("Window '%s' brightness=%.1f", title, brightness)
        if 50 < brightness < 220:
            log.info("Window '%s' loaded (brightness=%.1f)", title, brightness)
            return True
        if brightness == 0.0:
            zero_count += 1
            if zero_count >= 5:
                log.warning("Window '%s' brightness unreadable (DX capture issue)", title)
                return False
        else:
            zero_count = 0  # reset if we get a non-zero reading (e.g. 255)
        time.sleep(2.0)
    log.warning("Window '%s' did not load within timeout", title)
    return False


def send_start_sequence(hwnd, title):
    """Bring window to foreground and send keys to start a new run.

    Sequence: Enter (skip intro) -> Enter (skip title page) ->
    Right (move to middle save file) -> Enter (select save file) ->
    Enter (continue/new run) -> Enter (confirm character if new run).
    """
    log.info("Sending start keys to: %s", title)
    # for vk, delay in [
    #     (VK_RETURN, 1.5),   # skip intro
    #     (VK_RETURN, 1.5),   # skip title page
    #     (VK_RIGHT, 1.5),    # move to middle save file
    #     (VK_RETURN, 1.5),   # select save file
    #     (VK_RETURN, 0.5),   # continue/new run
    #     (VK_RETURN, 0.3),   # confirm character if new run
    # ]:
    
    for vk, delay in [
        (VK_RETURN, 0.3),   # Enter go Brrrr
        (VK_RETURN, 0.3),   # rrrrrrrrrrrrrr
        (VK_RETURN, 0.3),   # rrrrrrrrrrrrrr
        (VK_RETURN, 0.3),   # rrrrrrrrrrrrrr
        (VK_RETURN, 0.3),   # rrrrrrrrrrrrrr
        (VK_RETURN, 0.3),   # rrrrrrrrrrrrrr
        (VK_RETURN, 0.3),   # rrrrrrrrrrrrrr
        (VK_RETURN, 0.3),   # rrrrrrrrrrrrrr
        (VK_RETURN, 0.3),   # rrrrrrrrrrrrrr
        (VK_RETURN, 0.3),   # rrrrrrrrrrrrrr
        (VK_RETURN, 0.3),   # rrrrrrrrrrrrrr
        (VK_RETURN, 0.3),   # rrrrrrrrrrrrrr
    ]:
        _send_key(hwnd, vk)
        time.sleep(delay)


# ---------- Core launcher ----------

def sandbox_name(worker_id: int) -> str:
    return f"{SANDBOX_PREFIX}{worker_id}"


def launch_worker(worker_id: int, port: int) -> subprocess.Popen:
    """Launch Isaac inside a Sandboxie sandbox with the given port."""
    box = sandbox_name(worker_id)
    cmd = [
        SANDBOXIE_START,
        f"/box:{box}",
        f"/env:ISAAC_RL_PORT={port}",
        f"/env:ISAAC_RL_INSTANCE={worker_id}",
        STEAM_EXE,
        "-offline",
        "-silent",
        "-applaunch",
        ISAAC_APP_ID,
    ]
    log.info("Launching worker %d in sandbox %s on port %d", worker_id, box, port)
    log.debug("Command: %s", cmd)
    proc = subprocess.Popen(cmd)
    return proc


def _tasklist_running(image_name: str) -> bool:
    """Check whether an image is running using Windows tasklist."""
    cmd = ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False
    output = (result.stdout or "").lower()
    if "no tasks are running" in output:
        return False
    return image_name.lower() in output


def is_cheat_engine_running() -> bool:
    """Return True if any known Cheat Engine executable is already running."""
    return any(_tasklist_running(name) for name in CHEAT_ENGINE_PROCESS_CANDIDATES)


def find_cheat_engine_exe() -> Optional[Path]:
    """Return an installed Cheat Engine executable path, or None if missing."""
    for exe_name in CHEAT_ENGINE_EXE_CANDIDATES:
        exe_path = Path(CHEAT_ENGINE_DIR, exe_name)
        if exe_path.exists():
            return exe_path
    return None


def reinstall_ce_autorun(repo_root: Path, speed: float, scan_ms: int) -> bool:
    """Reinstall CE autorun script so watcher settings are refreshed."""
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
    repo_root: Path,
    reinstall_autorun: bool,
    ce_speed: float,
    ce_scan_ms: int,
    ce_startup_delay: float,
) -> bool:
    """Ensure CE is running before workers launch, optionally reinstalling autorun."""
    if reinstall_autorun:
        if not reinstall_ce_autorun(repo_root, ce_speed, ce_scan_ms):
            return False
    elif not CHEAT_ENGINE_AUTORUN_FILE.exists():
        log.warning(
            "CE autorun script not found at %s. "
            "Use --ce-reinstall-autorun once to install it.",
            CHEAT_ENGINE_AUTORUN_FILE,
        )

    if is_cheat_engine_running():
        log.info("Cheat Engine already running.")
        return True

    ce_exe = find_cheat_engine_exe()
    if ce_exe is None:
        log.error(
            "Cheat Engine executable not found in %s. "
            "Install CE or launch it manually before running workers.",
            CHEAT_ENGINE_DIR,
        )
        return False

    log.info("Launching Cheat Engine: %s", ce_exe)
    subprocess.Popen([str(ce_exe)])
    if ce_startup_delay > 0:
        time.sleep(ce_startup_delay)
    return True


def wait_for_port(host: str, port: int, timeout: float = 120.0) -> bool:
    """Wait until a TCP port is accepting connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except (ConnectionRefusedError, TimeoutError, OSError):
            time.sleep(2.0)
    return False



def terminate_all(n_workers: int):
    """Terminate all worker sandboxes."""
    for i in range(1, n_workers + 1):
        box = sandbox_name(i)
        cmd = [SANDBOXIE_START, f"/box:{box}", "/terminate"]
        log.info("Terminating sandbox %s", box)
        subprocess.run(cmd, capture_output=True)


def auto_start_runs(n_workers: int, timeout: float = 120.0):
    """Wait for Isaac windows to load, then send key sequences to start runs."""
    log.info("Waiting for %d Isaac windows...", n_workers)
    deadline = time.monotonic() + timeout
    windows = []
    while time.monotonic() < deadline and len(windows) < n_workers:
        windows = find_isaac_windows()
        if len(windows) < n_workers:
            time.sleep(2.0)

    if not windows:
        log.error("No Isaac windows found. Skipping auto-start.")
        return False

    if len(windows) < n_workers:
        log.warning("Found %d/%d Isaac windows.", len(windows), n_workers)

    # Try brightness detection first for each window
    for i, (hwnd, title) in enumerate(windows, 1):
        log.info("Checking window %d/%d: '%s' (hwnd=%s)", i, len(windows), title, hwnd)
        if wait_for_window_loaded(hwnd, title, timeout=30.0):
            send_start_sequence(hwnd, title)
            time.sleep(2.0)

    # Always offer manual prompt to (re)send keys to all windows
    input(">>> Press Enter to send start keys to ALL windows...")
    for hwnd, title in windows:
        send_start_sequence(hwnd, title)
        time.sleep(2.0)

    return True


def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Launch Isaac RL workers in Sandboxie")
    parser.add_argument("--workers", type=int, default=2, help="Number of workers")
    parser.add_argument("--base-port", type=int, default=DEFAULT_BASE_PORT, help="Base TCP port")
    parser.add_argument("--terminate", action="store_true", help="Terminate all workers")
    parser.add_argument("--timeout", type=float, default=120.0, help="Connection timeout per worker")
    parser.add_argument("--no-auto-start", action="store_true",
                        help="Skip auto-start (manually start runs in each window)")
    parser.add_argument(
        "--no-ce",
        action="store_true",
        help="Skip ensuring Cheat Engine is running before worker launch",
    )
    parser.add_argument(
        "--ce-reinstall-autorun",
        action="store_true",
        help="Reinstall CE speedhack autorun script before launching workers",
    )
    parser.add_argument(
        "--ce-speed",
        type=float,
        default=10.0,
        help="Speed used when --ce-reinstall-autorun is set",
    )
    parser.add_argument(
        "--ce-scan-ms",
        type=int,
        default=1000,
        help="Scan interval used when --ce-reinstall-autorun is set",
    )
    parser.add_argument(
        "--ce-startup-delay",
        type=float,
        default=2.0,
        help="Delay after launching CE to let autorun watcher initialize",
    )
    args = parser.parse_args()

    if args.terminate:
        terminate_all(args.workers)
        return

    if not args.no_ce:
        repo_root = Path(__file__).resolve().parents[1]
        if not ensure_cheat_engine_running(
            repo_root=repo_root,
            reinstall_autorun=args.ce_reinstall_autorun,
            ce_speed=args.ce_speed,
            ce_scan_ms=args.ce_scan_ms,
            ce_startup_delay=args.ce_startup_delay,
        ):
            sys.exit(1)
    else:
        log.info("Skipping Cheat Engine pre-launch checks (--no-ce).")

    # Launch workers
    procs = []
    for i in range(1, args.workers + 1):
        port = args.base_port + (i - 1)
        proc = launch_worker(i, port)
        procs.append((i, port, proc))
        if i < args.workers:
            time.sleep(3.0)

    # Auto-start runs via pixel detection + keypresses
    if not args.no_auto_start:
        auto_start_runs(args.workers, timeout=args.timeout)
    else:
        log.info("Auto-start disabled. Start a run in each Isaac window manually.")

    # Wait for all workers to accept TCP connections
    log.info("Waiting for %d workers to become reachable...", args.workers)
    all_ready = True
    for worker_id, port, _proc in procs:
        log.info("Waiting for worker %d on port %d...", worker_id, port)
        if wait_for_port("127.0.0.1", port, timeout=args.timeout):
            log.info("Worker %d ready on port %d", worker_id, port)
        else:
            log.error("Worker %d on port %d did not become reachable", worker_id, port)
            all_ready = False

    if all_ready:
        log.info("All %d workers ready! Start training with:", args.workers)
        log.info("  python train.py --config <config.yaml>")
        log.info("  (set env.n_workers=%d and env.base_port=%d in config)",
                 args.workers, args.base_port)
    else:
        log.error("Some workers failed to start. Check Sandboxie and game logs.")
        sys.exit(1)

    # Keep running until Ctrl+C
    log.info("Press Ctrl+C to terminate all workers")
    try:
        while True:
            time.sleep(5.0)
    except KeyboardInterrupt:
        log.info("Shutting down workers...")
        terminate_all(args.workers)
        log.info("Done.")


if __name__ == "__main__":
    main()
