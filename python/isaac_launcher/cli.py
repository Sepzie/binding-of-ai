from __future__ import annotations

import argparse
import logging
from logging import Handler, LogRecord
import sys
import time
from typing import Iterable

from .config import LauncherConfig
from .controller import LauncherController


class UILogHandler(Handler):
    def __init__(self, controller: LauncherController) -> None:
        super().__init__(level=logging.INFO)
        self.controller = controller

    def emit(self, record: LogRecord) -> None:
        if record.name.startswith("prompt_toolkit"):
            return
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()
        self.controller.record_log_line(message)


def _configure_logging(mode: str, controller: LauncherController | None = None) -> None:
    if mode == "tui":
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.INFO)
        if controller is not None:
            handler = UILogHandler(controller)
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(name)s] %(message)s",
                    datefmt="%H:%M:%S",
                )
            )
            root.addHandler(handler)
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


def _parse_worker_ids(raw: str, max_workers: int) -> list[int]:
    if not raw.strip():
        return list(range(1, max_workers + 1))
    worker_ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        worker_id = int(part)
        if 1 <= worker_id <= max_workers and worker_id not in worker_ids:
            worker_ids.append(worker_id)
    return worker_ids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch and manage Isaac RL workers")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("launch", "tui", "terminate"),
        default="launch",
        help="launch workers headlessly, open the TUI, or terminate workers",
    )
    parser.add_argument("--workers", type=int, default=2, help="Number of workers")
    parser.add_argument("--base-port", type=int, default=9999, help="Base TCP port")
    parser.add_argument("--batch-size", type=int, default=4, help="Workers to launch per batch")
    parser.add_argument("--timeout", type=float, default=120.0, help="Timeout per wait operation")
    parser.add_argument(
        "--inter-launch-delay",
        type=float,
        default=3.0,
        help="Delay between worker launches within a batch",
    )
    parser.add_argument(
        "--batch-settle-delay",
        type=float,
        default=10.0,
        help="Extra wait after window detection if load checks are inconclusive",
    )
    parser.add_argument("--no-auto-start", action="store_true", help="Skip automatic start sequences")
    parser.add_argument("--no-ce", action="store_true", help="Skip Cheat Engine checks")
    parser.add_argument(
        "--ce-reinstall-autorun",
        action="store_true",
        help="Reinstall the CE autorun script before worker launch",
    )
    parser.add_argument("--ce-speed", type=float, default=10.0, help="CE speed for autorun install")
    parser.add_argument("--ce-scan-ms", type=int, default=1000, help="CE watch scan interval")
    parser.add_argument(
        "--ce-startup-delay",
        type=float,
        default=2.0,
        help="Delay after launching Cheat Engine",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Background refresh interval for launcher monitoring",
    )
    parser.add_argument(
        "--brightness-refresh-interval",
        type=float,
        default=6.0,
        help="How often the TUI samples window brightness",
    )
    parser.add_argument(
        "--worker-ids",
        type=str,
        default="",
        help="Comma-separated worker ids for terminate operations",
    )
    parser.add_argument(
        "--detach",
        action="store_true",
        help="Exit after workers are ready instead of holding the process open",
    )
    return parser


def _make_config(args: argparse.Namespace) -> LauncherConfig:
    return LauncherConfig(
        workers=args.workers,
        base_port=args.base_port,
        batch_size=args.batch_size,
        timeout=args.timeout,
        inter_launch_delay=args.inter_launch_delay,
        batch_settle_delay=args.batch_settle_delay,
        auto_start=not args.no_auto_start,
        ensure_ce=not args.no_ce,
        ce_reinstall_autorun=args.ce_reinstall_autorun,
        ce_speed=args.ce_speed,
        ce_scan_ms=args.ce_scan_ms,
        ce_startup_delay=args.ce_startup_delay,
        poll_interval=args.poll_interval,
        brightness_refresh_interval=args.brightness_refresh_interval,
    )


def _hold_until_interrupt(controller: LauncherController) -> None:
    controller.append_log("Press Ctrl+C to terminate all workers.")
    try:
        while True:
            time.sleep(5.0)
    except KeyboardInterrupt:
        controller.append_log("Shutting down all workers.")
        controller.terminate_workers(controller.worker_ids())


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    _configure_logging(args.command)
    config = _make_config(args)
    controller = LauncherController(config)

    if args.command == "terminate":
        worker_ids = _parse_worker_ids(args.worker_ids, args.workers)
        controller.terminate_workers(worker_ids)
        return 0

    if args.command == "tui":
        controller.set_logger_echo(False)
        _configure_logging("tui", controller)
        from .tui import run_tui

        run_tui(controller)
        return 0

    ok = controller.headless_launch()
    if not ok:
        return 1
    if args.detach:
        return 0
    _hold_until_interrupt(controller)
    return 0


if __name__ == "__main__":
    sys.exit(main())
