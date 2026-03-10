"""Launcher for multi-instance Isaac RL training via Sandboxie-Plus.

Starts N Isaac game instances in separate Sandboxie sandboxes, each with a
unique TCP port, then waits for all workers to become reachable.

Usage:
    python launcher.py --workers 2
    python launcher.py --workers 3 --base-port 9999
    python launcher.py --terminate  # kill all workers
"""

import argparse
import logging
import socket
import subprocess
import sys
import time

log = logging.getLogger("launcher")

SANDBOXIE_START = r"C:\Program Files\Sandboxie-Plus\Start.exe"
STEAM_EXE = r"C:\Program Files (x86)\Steam\steam.exe"
ISAAC_APP_ID = "250900"
SANDBOX_PREFIX = "IsaacWorker"
DEFAULT_BASE_PORT = 9999


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
        # Stagger launches slightly to avoid Steam conflicts
        if i < args.workers:
            time.sleep(3.0)

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
        log.info("NOTE: You must manually start a run in each Isaac window first.")
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
