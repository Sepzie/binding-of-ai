from __future__ import annotations

from collections import deque
from dataclasses import replace
import logging
from pathlib import Path
import threading
import time
from typing import Iterable

from . import actions, discovery
from .config import LauncherConfig, LauncherPaths, default_paths, repo_root
from .models import WorkerState

log = logging.getLogger("isaac_launcher.controller")


class LauncherController:
    def __init__(
        self,
        config: LauncherConfig,
        paths: LauncherPaths | None = None,
        repo_path: Path | None = None,
    ) -> None:
        self.config = config
        self.paths = paths or default_paths()
        self.repo_root = repo_path or repo_root()
        self._lock = threading.RLock()
        self._echo_to_logger = True
        self._worker_hwnds: dict[int, int] = {}
        self._launch_requested: set[int] = set()
        self._last_action: dict[int, str] = {}
        self._last_error: dict[int, str] = {}
        self._logs: deque[str] = deque(maxlen=250)
        self._last_snapshot: list[WorkerState] = []
        self._tcp_status_cache: dict[int, tuple[bool, float]] = {}
        self._brightness_cache: dict[int, tuple[int, float | None, bool, float]] = {}
        self.append_log("Launcher controller initialized.")

    def worker_ids(self) -> list[int]:
        return self.config.worker_ids()

    def set_logger_echo(self, enabled: bool) -> None:
        with self._lock:
            self._echo_to_logger = enabled

    def record_log_line(self, message: str) -> None:
        with self._lock:
            self._logs.append(message)

    def append_log(self, message: str, level: int = logging.INFO) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.record_log_line(f"{timestamp} {message}")
        with self._lock:
            echo = self._echo_to_logger
        if echo:
            log.log(level, message)

    def render_logs(self, limit: int = 200) -> str:
        with self._lock:
            return "\n".join(list(self._logs)[-limit:])

    def _normalize_worker_ids(self, worker_ids: Iterable[int] | None) -> list[int]:
        valid = set(self.worker_ids())
        if worker_ids is None:
            return self.worker_ids()
        normalized = []
        for worker_id in worker_ids:
            if worker_id in valid and worker_id not in normalized:
                normalized.append(worker_id)
        return normalized

    def _state_template(self, worker_id: int) -> WorkerState:
        return WorkerState(
            worker_id=worker_id,
            sandbox_name=self.config.sandbox_name(self.paths, worker_id),
            port=self.config.port_for(worker_id),
            launch_requested=worker_id in self._launch_requested,
            last_action=self._last_action.get(worker_id, ""),
            last_error=self._last_error.get(worker_id, ""),
        )

    def _assign_windows(self, worker_ids: list[int], windows) -> None:
        with self._lock:
            for worker_id, window in zip(worker_ids, sorted(windows, key=lambda item: item.hwnd)):
                self._worker_hwnds[worker_id] = window.hwnd
                self._last_action[worker_id] = f"Window {window.hwnd} assigned"

    def _tcp_probe_interval(self, state: WorkerState, cached_ready: bool) -> float:
        if state.launch_requested:
            return max(0.5, self.config.poll_interval)
        if state.window_visible and not state.tcp_ready:
            return max(0.5, self.config.poll_interval)
        if cached_ready:
            return 5.0
        return 15.0

    def _get_cached_tcp_ready(self, state: WorkerState, now: float) -> bool:
        cached_ready, cached_at = self._tcp_status_cache.get(state.worker_id, (False, 0.0))
        interval = self._tcp_probe_interval(state, cached_ready)
        should_probe = (
            state.launch_requested
            or state.window_visible
            or cached_ready
            or (now - cached_at) >= interval
        )
        if should_probe:
            cached_ready = discovery.probe_port(self.config.host, state.port)
            self._tcp_status_cache[state.worker_id] = (cached_ready, now)
        return cached_ready

    def _get_cached_brightness(
        self,
        worker_id: int,
        hwnd: int | None,
        include_brightness: bool,
        now: float,
    ) -> tuple[float | None, bool]:
        if hwnd is None:
            self._brightness_cache.pop(worker_id, None)
            return None, False

        cached = self._brightness_cache.get(worker_id)
        if cached is not None:
            cached_hwnd, cached_value, cached_loaded, cached_at = cached
            if cached_hwnd == hwnd and (not include_brightness or (now - cached_at) < self.config.brightness_refresh_interval):
                return cached_value, cached_loaded

        if not include_brightness:
            return None, False

        brightness = discovery.window_brightness(hwnd)
        loaded = brightness is not None and 50 < brightness < 220
        self._brightness_cache[worker_id] = (hwnd, brightness, loaded, now)
        return brightness, loaded

    def refresh_states(self, include_brightness: bool = False) -> list[WorkerState]:
        windows = {window.hwnd: window for window in discovery.find_isaac_windows()}
        now = time.monotonic()

        with self._lock:
            worker_hwnds = {
                worker_id: hwnd
                for worker_id, hwnd in self._worker_hwnds.items()
                if hwnd in windows
            }
            assigned_hwnds = set(worker_hwnds.values())
            unassigned_windows = [window for hwnd, window in windows.items() if hwnd not in assigned_hwnds]
            unassigned_windows.sort(key=lambda window: window.hwnd)
            unmapped_workers = [worker_id for worker_id in self.worker_ids() if worker_id not in worker_hwnds]
            for worker_id, window in zip(unmapped_workers, unassigned_windows):
                worker_hwnds[worker_id] = window.hwnd

            launch_requested = set(self._launch_requested)
            last_action = dict(self._last_action)
            last_error = dict(self._last_error)

        snapshot: list[WorkerState] = []
        ready_workers: list[int] = []
        for worker_id in self.worker_ids():
            state = WorkerState(
                worker_id=worker_id,
                sandbox_name=self.config.sandbox_name(self.paths, worker_id),
                port=self.config.port_for(worker_id),
                launch_requested=worker_id in launch_requested,
                last_action=last_action.get(worker_id, ""),
                last_error=last_error.get(worker_id, ""),
            )
            hwnd = worker_hwnds.get(worker_id)
            if hwnd is not None and hwnd in windows:
                window = windows[hwnd]
                state.hwnd = window.hwnd
                state.title = window.title
                state.pid = window.pid
                state.window_visible = True

            state.tcp_ready = self._get_cached_tcp_ready(state, now)
            if state.window_visible:
                state.brightness, state.loaded = self._get_cached_brightness(
                    worker_id,
                    state.hwnd,
                    include_brightness,
                    now,
                )
            else:
                state.brightness = None
                state.loaded = False
                self._brightness_cache.pop(worker_id, None)

            if state.tcp_ready:
                ready_workers.append(worker_id)
                if not state.last_action:
                    state.last_action = "TCP ready"

            snapshot.append(state)

        with self._lock:
            self._worker_hwnds = worker_hwnds
            for worker_id in ready_workers:
                self._launch_requested.discard(worker_id)
            self._last_snapshot = snapshot
            return [replace(state) for state in snapshot]

    def ensure_cheat_engine(self) -> bool:
        ok = actions.ensure_cheat_engine_running(
            self.paths,
            self.repo_root,
            reinstall_autorun=self.config.ce_reinstall_autorun,
            ce_speed=self.config.ce_speed,
            ce_scan_ms=self.config.ce_scan_ms,
            ce_startup_delay=self.config.ce_startup_delay,
        )
        self.append_log("Cheat Engine ready." if ok else "Cheat Engine not ready.")
        return ok

    def launch_workers(
        self,
        worker_ids: Iterable[int],
        ensure_ce: bool = True,
        auto_start: bool | None = None,
    ) -> bool:
        target_ids = self._normalize_worker_ids(worker_ids)
        if not target_ids:
            return True
        if auto_start is None:
            auto_start = self.config.auto_start

        if ensure_ce and self.config.ensure_ce and not self.ensure_cheat_engine():
            return False

        current = {state.worker_id: state for state in self.refresh_states(include_brightness=False)}
        pending = []
        for worker_id in target_ids:
            state = current[worker_id]
            if state.window_visible or state.tcp_ready:
                self.append_log(f"Worker {worker_id} already active; skipping launch.")
                continue
            pending.append(worker_id)

        if not pending:
            return True

        existing_hwnds = {window.hwnd for window in discovery.find_isaac_windows()}
        for index, worker_id in enumerate(pending):
            actions.launch_worker(self.paths, worker_id, self.config.port_for(worker_id))
            with self._lock:
                self._launch_requested.add(worker_id)
                self._last_action[worker_id] = "Launch requested"
                self._last_error.pop(worker_id, None)
            self.append_log(f"Launched worker {worker_id} on port {self.config.port_for(worker_id)}.")
            if index < len(pending) - 1 and self.config.inter_launch_delay > 0:
                time.sleep(self.config.inter_launch_delay)

        new_windows = discovery.wait_for_new_windows(
            existing_hwnds=existing_hwnds,
            expected_count=len(pending),
            timeout=self.config.timeout,
            poll_interval=self.config.poll_interval,
        )
        if len(new_windows) < len(pending):
            message = (
                f"Only detected {len(new_windows)}/{len(pending)} new window(s) for workers "
                f"{', '.join(str(worker_id) for worker_id in pending)}."
            )
            with self._lock:
                for worker_id in pending:
                    self._last_error[worker_id] = message
            self.append_log(message, level=logging.ERROR)
            return False

        self._assign_windows(pending, new_windows)
        loaded = discovery.wait_for_windows_ready(
            new_windows,
            timeout_per_window=min(self.config.timeout, 30.0),
            fallback_settle_delay=self.config.batch_settle_delay,
            poll_interval=self.config.poll_interval,
        )
        if loaded:
            self.append_log(f"Workers {', '.join(str(worker_id) for worker_id in pending)} reached a loaded window state.")
        else:
            self.append_log("Some windows did not confirm load state; continued after fallback delay.")

        if auto_start:
            self.send_start_to_workers(pending)
        return True

    def launch_workers_in_batches(
        self,
        worker_ids: Iterable[int] | None = None,
        auto_start: bool | None = None,
    ) -> bool:
        target_ids = self._normalize_worker_ids(worker_ids)
        if not target_ids:
            return True
        if self.config.ensure_ce and not self.ensure_cheat_engine():
            return False
        if auto_start is None:
            auto_start = self.config.auto_start

        batch_size = self.config.batch_size if self.config.batch_size > 0 else len(target_ids)
        for batch_start in range(0, len(target_ids), batch_size):
            batch = target_ids[batch_start: batch_start + batch_size]
            self.append_log(f"Launching batch: {', '.join(str(worker_id) for worker_id in batch)}")
            if not self.launch_workers(batch, ensure_ce=False, auto_start=auto_start):
                return False
        return True

    def send_start_to_workers(self, worker_ids: Iterable[int]) -> bool:
        target_ids = self._normalize_worker_ids(worker_ids)
        if not target_ids:
            return True
        states = {state.worker_id: state for state in self.refresh_states(include_brightness=False)}
        sent = 0
        for worker_id in target_ids:
            state = states[worker_id]
            if not state.window_visible or state.hwnd is None:
                self.append_log(f"Worker {worker_id} has no visible window; skipping start sequence.")
                continue
            actions.send_start_sequence(state.hwnd, state.title or f"Worker {worker_id}")
            with self._lock:
                self._last_action[worker_id] = "Start sequence sent"
                self._last_error.pop(worker_id, None)
            self.append_log(f"Sent start sequence to worker {worker_id}.")
            sent += 1
        return sent > 0

    def launch_and_start_workers(self, worker_ids: Iterable[int]) -> bool:
        target_ids = self._normalize_worker_ids(worker_ids)
        if not target_ids:
            return True

        states = {state.worker_id: state for state in self.refresh_states(include_brightness=False)}
        missing = [
            worker_id
            for worker_id in target_ids
            if not states[worker_id].window_visible and not states[worker_id].tcp_ready
        ]
        if missing:
            self.append_log(
                f"Launching missing workers before start: {', '.join(str(worker_id) for worker_id in missing)}"
            )
            if not self.launch_workers(missing, auto_start=True):
                return False

        already_present = [worker_id for worker_id in target_ids if worker_id not in missing]
        if not already_present:
            return True
        return self.send_start_to_workers(already_present)

    def send_start_to_visible_workers(self) -> bool:
        states = self.refresh_states(include_brightness=False)
        visible = [state.worker_id for state in states if state.window_visible]
        return self.send_start_to_workers(visible)

    def terminate_workers(self, worker_ids: Iterable[int]) -> None:
        target_ids = self._normalize_worker_ids(worker_ids)
        if not target_ids:
            return
        for worker_id in target_ids:
            actions.terminate_worker(self.paths, worker_id)
            with self._lock:
                self._worker_hwnds.pop(worker_id, None)
                self._launch_requested.discard(worker_id)
                self._last_action[worker_id] = "Sandbox terminated"
                self._last_error.pop(worker_id, None)
            self.append_log(f"Terminated worker {worker_id}.")

    def wait_for_ports(self, worker_ids: Iterable[int]) -> bool:
        target_ids = self._normalize_worker_ids(worker_ids)
        all_ready = True
        for worker_id in target_ids:
            port = self.config.port_for(worker_id)
            self.append_log(f"Waiting for worker {worker_id} on port {port}.")
            ready = discovery.wait_for_port(
                self.config.host,
                port,
                timeout=self.config.timeout,
                poll_interval=self.config.poll_interval,
            )
            if ready:
                with self._lock:
                    self._last_action[worker_id] = "TCP ready"
                    self._last_error.pop(worker_id, None)
                self.append_log(f"Worker {worker_id} ready on port {port}.")
            else:
                with self._lock:
                    self._last_error[worker_id] = f"Port {port} never became reachable"
                self.append_log(f"Worker {worker_id} on port {port} did not become reachable.", level=logging.ERROR)
                all_ready = False
        return all_ready

    def headless_launch(self) -> bool:
        self.append_log(
            f"Using staged launch for {self.config.workers} worker(s); batch size "
            f"{self.config.batch_size if self.config.batch_size > 0 else self.config.workers}."
        )
        if not self.launch_workers_in_batches(auto_start=self.config.auto_start):
            return False
        if not self.config.auto_start:
            self.append_log("Auto-start disabled; start each window manually.")
        return self.wait_for_ports(self.worker_ids())
