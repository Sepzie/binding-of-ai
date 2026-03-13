from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IsaacWindow:
    hwnd: int
    title: str
    pid: int | None = None


@dataclass
class WorkerState:
    worker_id: int
    sandbox_name: str
    port: int
    hwnd: int | None = None
    title: str = ""
    pid: int | None = None
    window_visible: bool = False
    tcp_ready: bool = False
    loaded: bool = False
    brightness: float | None = None
    launch_requested: bool = False
    last_action: str = ""
    last_error: str = ""

    @property
    def status(self) -> str:
        if self.last_error:
            return "error"
        if self.tcp_ready and self.loaded:
            return "ready"
        if self.tcp_ready:
            return "tcp"
        if self.window_visible and self.loaded:
            return "loaded"
        if self.window_visible:
            return "window"
        if self.launch_requested:
            return "launching"
        return "idle"

    @property
    def brightness_text(self) -> str:
        if self.brightness is None:
            return "--"
        return f"{self.brightness:.0f}"

    @property
    def note(self) -> str:
        if self.last_error:
            return self.last_error
        if self.last_action:
            return self.last_action
        if self.tcp_ready:
            return "TCP ready"
        if self.window_visible:
            return self.title or "Window detected"
        if self.launch_requested:
            return "Launch requested"
        return "Idle"
