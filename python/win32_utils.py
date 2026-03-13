import ctypes
import ctypes.wintypes
from pathlib import Path
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101

VK_RETURN = 0x0D
VK_RIGHT = 0x27

SC_ENTER = 0x1C
SC_RIGHT = 0x4D

_VK_TO_SC = {VK_RETURN: SC_ENTER, VK_RIGHT: SC_RIGHT}
_EXTENDED_KEYS = {VK_RIGHT}

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def send_key(hwnd, vk_code: int, press_delay: float = 0.05) -> None:
    """Send a keypress to a window via PostMessage."""
    sc = _VK_TO_SC.get(vk_code, 0)
    extended = (1 << 24) if vk_code in _EXTENDED_KEYS else 0
    lparam_down = extended | (sc << 16) | 1
    lparam_up = extended | (sc << 16) | 1 | (1 << 30) | (1 << 31)
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk_code, lparam_down)
    time.sleep(press_delay)
    user32.PostMessageW(hwnd, WM_KEYUP, vk_code, lparam_up)


def get_pid_from_hwnd(hwnd) -> int:
    """Get the process ID that owns the given window handle."""
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_window_rect(hwnd) -> tuple[int, int, int, int]:
    """Get window bounding box as (left, top, right, bottom)."""
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def get_process_image_name(pid: int) -> str | None:
    """Return the basename of the executable for a process id."""
    if pid <= 0:
        return None

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None

    try:
        size = ctypes.wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name.lower()
        return None
    finally:
        kernel32.CloseHandle(handle)
