from __future__ import annotations

import threading
import time

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame

from .controller import LauncherController
from .models import WorkerState


class LauncherTUI:
    def __init__(self, controller: LauncherController) -> None:
        self.controller = controller
        self.states = controller.refresh_states(include_brightness=True)
        self.cursor = 0
        self.selected: set[int] = set()
        self.active_action = "idle"
        self._stop = threading.Event()
        self._action_lock = threading.Lock()
        self.header = Window(FormattedTextControl(self._render_header), height=2)
        self.table = Window(FormattedTextControl(self._render_table), always_hide_cursor=True)
        self.details = Window(FormattedTextControl(self._render_details), always_hide_cursor=True)
        self.log_area = Window(
            FormattedTextControl(self._render_logs),
            always_hide_cursor=True,
            wrap_lines=False,
        )
        self.footer = Window(FormattedTextControl(self._render_footer), height=2)
        root = HSplit(
            [
                Frame(self.header, title="Isaac Launcher"),
                VSplit(
                    [
                        Frame(self.table, title="Workers"),
                        Frame(self.details, title="Details"),
                    ],
                    padding=1,
                ),
                Frame(self.log_area, title="Event Log", height=12),
                self.footer,
            ]
        )
        self.app = Application(
            layout=Layout(root),
            key_bindings=self._bindings(),
            style=self._style(),
            full_screen=True,
        )
        self._refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)

    def _style(self) -> Style:
        return Style.from_dict(
            {
                "frame.label": "bg:#0f172a #e2e8f0 bold",
                "status": "#93c5fd",
                "status.good": "#86efac",
                "status.warn": "#fcd34d",
                "status.bad": "#fca5a5",
                "row": "#cbd5e1",
                "row.cursor": "bg:#164e63 #f8fafc",
                "row.selected": "bg:#3f6212 #f8fafc",
                "row.cursor-selected": "bg:#365314 #f8fafc bold",
                "header": "bg:#082f49 #e0f2fe bold",
                "footer": "bg:#1e293b #e2e8f0",
                "detail.key": "#7dd3fc bold",
                "detail.value": "#f8fafc",
            }
        )

    def _bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        def _move_up(_event) -> None:
            if self.states:
                self.cursor = max(0, self.cursor - 1)
                self.app.invalidate()

        @kb.add("down")
        def _move_down(_event) -> None:
            if self.states:
                self.cursor = min(len(self.states) - 1, self.cursor + 1)
                self.app.invalidate()

        @kb.add(" ")
        @kb.add("enter")
        def _toggle(_event) -> None:
            state = self._current_state()
            if state is None:
                return
            if state.worker_id in self.selected:
                self.selected.remove(state.worker_id)
            else:
                self.selected.add(state.worker_id)
            self.app.invalidate()

        @kb.add("escape")
        def _clear(_event) -> None:
            self.selected.clear()
            self.app.invalidate()

        @kb.add("r")
        def _refresh(_event) -> None:
            self._run_action("Refresh", lambda: None, force_brightness=True, clear_selection=False)

        @kb.add("c")
        def _ce(_event) -> None:
            self._run_action("Ensure CE", self.controller.ensure_cheat_engine)

        @kb.add("l")
        def _launch_selected(_event) -> None:
            self._run_action("Launch selection", lambda: self.controller.launch_workers(self._active_worker_ids()))

        @kb.add("b")
        def _launch_batches(_event) -> None:
            self._run_action(
                "Launch batches",
                lambda: self.controller.launch_workers_in_batches(self._selected_or_all_worker_ids()),
            )

        @kb.add("s")
        def _start_selected(_event) -> None:
            self._run_action(
                "Launch + start selection",
                lambda: self.controller.launch_and_start_workers(self._active_worker_ids()),
            )

        @kb.add("a")
        def _start_visible(_event) -> None:
            self._run_action("Start visible", self.controller.send_start_to_visible_workers)

        @kb.add("t")
        def _terminate_selected(_event) -> None:
            self._run_action("Terminate selection", lambda: self.controller.terminate_workers(self._active_worker_ids()))

        @kb.add("q")
        @kb.add("c-c")
        def _quit(event) -> None:
            self._stop.set()
            event.app.exit()

        return kb

    def _active_worker_ids(self) -> list[int]:
        if self.selected:
            return sorted(self.selected)
        state = self._current_state()
        return [state.worker_id] if state is not None else []

    def _selected_or_all_worker_ids(self) -> list[int]:
        if self.selected:
            return sorted(self.selected)
        return [state.worker_id for state in self.states]

    def _current_state(self) -> WorkerState | None:
        if not self.states:
            return None
        self.cursor = max(0, min(self.cursor, len(self.states) - 1))
        return self.states[self.cursor]

    def _summary(self) -> tuple[int, int, int]:
        ready = sum(1 for state in self.states if state.tcp_ready)
        windows = sum(1 for state in self.states if state.window_visible)
        selected = len(self.selected)
        return ready, windows, selected

    def _render_header(self):
        ready, windows, selected = self._summary()
        line = (
            f"  Workers {len(self.states)}  |  Visible {windows}  |  Ready {ready}  |  "
            f"Selected {selected}  |  Action {self.active_action}"
        )
        return [("class:header", line)]

    def _row_style(self, worker_id: int, is_cursor: bool) -> str:
        if worker_id in self.selected and is_cursor:
            return "class:row.cursor-selected"
        if worker_id in self.selected:
            return "class:row.selected"
        if is_cursor:
            return "class:row.cursor"
        return "class:row"

    def _render_table(self):
        fragments = [("class:header", " Sel Worker Port  Status     Win  TCP  Load Bright Note\n")]
        for index, state in enumerate(self.states):
            is_cursor = index == self.cursor
            style = self._row_style(state.worker_id, is_cursor)
            marker = "*" if state.worker_id in self.selected else " "
            win_flag = "yes" if state.window_visible else " no"
            tcp_flag = "yes" if state.tcp_ready else " no"
            load_flag = "yes" if state.loaded else " no"
            note = state.note[:36]
            row = (
                f"  {marker}   {state.worker_id:>2}   {state.port:>5}  {state.status:<10} "
                f"{win_flag:>4} {tcp_flag:>4} {load_flag:>5} {state.brightness_text:>6} {note}\n"
            )
            fragments.append((style, row))
        if not self.states:
            fragments.append(("class:row", "  No workers configured.\n"))
        return fragments

    def _render_details(self):
        state = self._current_state()
        if state is None:
            return [("class:detail.value", "No worker selected.")]
        details = [
            ("Worker", str(state.worker_id)),
            ("Sandbox", state.sandbox_name),
            ("Port", str(state.port)),
            ("Status", state.status),
            ("Window", state.title or "--"),
            ("HWND", str(state.hwnd) if state.hwnd is not None else "--"),
            ("PID", str(state.pid) if state.pid is not None else "--"),
            ("Brightness", state.brightness_text),
            ("Action", state.last_action or "--"),
            ("Error", state.last_error or "--"),
        ]
        fragments = []
        for key, value in details:
            fragments.append(("class:detail.key", f"{key:<11}"))
            fragments.append(("class:detail.value", f" {value}\n"))
        return fragments

    def _render_footer(self):
        line = (
            "  up/down move  enter/space select  l launch  b batch-launch selection/all  "
            "s launch+start selected  a start visible  t terminate  c CE  r refresh  q quit"
        )
        return [("class:footer", line)]

    def _render_logs(self):
        lines = self.controller.render_logs().splitlines()
        if not lines:
            lines = ["No events yet."]
        return [("class:row", "\n".join(lines[-200:]))]

    def _refresh_now(self, force_brightness: bool = False) -> None:
        self.states = self.controller.refresh_states(include_brightness=force_brightness)
        self.app.invalidate()

    def _refresh_loop(self) -> None:
        last_brightness = 0.0
        while not self._stop.is_set():
            include_brightness = (time.monotonic() - last_brightness) >= self.controller.config.brightness_refresh_interval
            if include_brightness:
                last_brightness = time.monotonic()
            self.states = self.controller.refresh_states(include_brightness=include_brightness)
            if self.app.is_running:
                self.app.invalidate()
            self._stop.wait(self.controller.config.poll_interval)

    def _run_action(
        self,
        label: str,
        func,
        force_brightness: bool = True,
        clear_selection: bool = True,
    ) -> None:
        if self._action_lock.locked():
            self.controller.append_log("Another action is already running.")
            return

        def runner() -> None:
            with self._action_lock:
                self.active_action = label
                self.controller.append_log(f"Action started: {label}")
                try:
                    func()
                except Exception as exc:  # pragma: no cover - UI guardrail
                    self.controller.append_log(f"Action failed: {label}: {exc}")
                finally:
                    if clear_selection:
                        self.selected.clear()
                    self.active_action = "idle"
                    self._refresh_now(force_brightness=force_brightness)

        threading.Thread(target=runner, daemon=True).start()

    def run(self) -> None:
        self._refresh_thread.start()
        try:
            self.app.run()
        finally:
            self._stop.set()


def run_tui(controller: LauncherController) -> None:
    LauncherTUI(controller).run()
