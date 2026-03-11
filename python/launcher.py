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
import socket
import subprocess
import sys
import time

from PIL import ImageGrab

log = logging.getLogger("launcher")

SANDBOXIE_START = r"C:\Program Files\Sandboxie-Plus\Start.exe"
STEAM_EXE = r"C:\Program Files (x86)\Steam\steam.exe"
ISAAC_APP_ID = "250900"
SANDBOX_PREFIX = "IsaacWorker"
DEFAULT_BASE_PORT = 9999

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


def get_window_rect(hwnd):
    """Get window bounding box as (left, top, right, bottom)."""
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def window_brightness(hwnd) -> float:
    """Grab a screenshot of the window and return average pixel brightness."""
    rect = get_window_rect(hwnd)
    if rect[2] - rect[0] < 10 or rect[3] - rect[1] < 10:
        return 0.0
    try:
        img = ImageGrab.grab(bbox=rect)
        # Sample center region (avoid window chrome)
        w, h = img.size
        crop = img.crop((w // 4, h // 4, 3 * w // 4, 3 * h // 4))
        pixels = list(crop.getdata())
        if not pixels:
            return 0.0
        avg = sum(sum(p[:3]) / 3 for p in pixels) / len(pixels)
        return avg
    except Exception:
        return 0.0


def wait_for_window_loaded(hwnd, title, timeout=120.0) -> bool:
    """Wait until the window shows the title screen (not black, not white).

    Loading sequence: black (0) -> white splash (255) -> title screen (~20-80).
    We wait for brightness to land in the middle range, indicating the menu.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        brightness = window_brightness(hwnd)
        log.debug("Window '%s' brightness=%.1f", title, brightness)
        if 50 < brightness < 200:
            log.info("Window '%s' loaded (brightness=%.1f)", title, brightness)
            return True
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
    for vk, delay in [
        (VK_RETURN, 1.5),   # skip intro
        (VK_RETURN, 1.5),   # skip title page
        (VK_RIGHT, 1.5),    # move to middle save file
        (VK_RETURN, 1.5),   # select save file
        (VK_RETURN, 0.5),   # continue/new run
        (VK_RETURN, 0.3),   # confirm character if new run
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

    # Wait for each window to finish loading, then send keys
    for hwnd, title in windows:
        if wait_for_window_loaded(hwnd, title, timeout=max(30, deadline - time.monotonic())):
            send_start_sequence(hwnd, title)
            time.sleep(1.0)

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
    args = parser.parse_args()

    if args.terminate:
        terminate_all(args.workers)
        return

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
