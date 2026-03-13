from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import socket
import time

from PIL import Image

from win32_utils import get_pid_from_hwnd, get_window_rect

from .models import IsaacWindow

log = logging.getLogger("isaac_launcher.discovery")
user32 = ctypes.windll.user32


def find_isaac_windows() -> list[IsaacWindow]:
    """Return visible Isaac windows."""
    windows: list[IsaacWindow] = []

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if "isaac" in title.lower() and "steam" not in title.lower():
                    windows.append(IsaacWindow(hwnd=hwnd, title=title, pid=get_pid_from_hwnd(hwnd)))
        return True

    wnd_enum_proc = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LPARAM,
    )
    user32.EnumWindows(wnd_enum_proc(callback), 0)
    windows.sort(key=lambda window: window.hwnd)
    return windows


def window_brightness(hwnd: int) -> float | None:
    """Return average brightness for the window center region."""
    rect = get_window_rect(hwnd)
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]
    if width < 10 or height < 10:
        return None

    try:
        import win32gui
        import win32ui

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)
        ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)

        bmpinfo = bitmap.GetInfo()
        bmpstr = bitmap.GetBitmapBits(True)
        image = Image.frombuffer(
            "RGB",
            (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
            bmpstr,
            "raw",
            "BGRX",
            0,
            1,
        )

        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)

        iw, ih = image.size
        crop = image.crop((iw // 4, ih // 4, 3 * iw // 4, 3 * ih // 4))
        pixels = list(crop.getdata())
        if not pixels:
            return None
        return sum(sum(pixel[:3]) / 3 for pixel in pixels) / len(pixels)
    except Exception as exc:
        log.debug("window_brightness failed for hwnd=%s: %s", hwnd, exc)
        return None


def probe_port(host: str, port: int, timeout: float = 0.25) -> bool:
    """Return True when the port accepts a connection."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_port(host: str, port: int, timeout: float, poll_interval: float = 2.0) -> bool:
    """Wait until the port accepts connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe_port(host, port):
            return True
        time.sleep(poll_interval)
    return False


def wait_for_window_loaded(
    hwnd: int,
    title: str,
    timeout: float,
    poll_interval: float = 2.0,
) -> bool:
    """Wait until a window brightness suggests the title screen is visible."""
    deadline = time.monotonic() + timeout
    zero_count = 0
    while time.monotonic() < deadline:
        brightness = window_brightness(hwnd)
        log.debug("Window '%s' brightness=%s", title, brightness)
        if brightness is not None and 50 < brightness < 220:
            return True
        if brightness in (None, 0.0):
            zero_count += 1
            if zero_count >= 5:
                return False
        else:
            zero_count = 0
        time.sleep(poll_interval)
    return False


def wait_for_new_windows(
    existing_hwnds: set[int],
    expected_count: int,
    timeout: float,
    poll_interval: float = 2.0,
) -> list[IsaacWindow]:
    """Wait until a specific number of new Isaac windows appear."""
    deadline = time.monotonic() + timeout
    latest: list[IsaacWindow] = []
    while time.monotonic() < deadline:
        windows = find_isaac_windows()
        latest = [window for window in windows if window.hwnd not in existing_hwnds]
        if len(latest) >= expected_count:
            return latest[:expected_count]
        time.sleep(poll_interval)
    return latest


def wait_for_windows_ready(
    windows: list[IsaacWindow],
    timeout_per_window: float,
    fallback_settle_delay: float,
    poll_interval: float = 2.0,
) -> bool:
    """Wait for windows to settle enough for the next launch stage."""
    unsettled: list[IsaacWindow] = []
    for window in windows:
        if wait_for_window_loaded(window.hwnd, window.title, timeout_per_window, poll_interval):
            continue
        unsettled.append(window)

    if unsettled and fallback_settle_delay > 0:
        time.sleep(fallback_settle_delay)
    return not unsettled
