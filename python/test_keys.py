"""Send the full start sequence to Isaac via PostMessage.

Sequence: Enter → Enter → Right → Enter → Enter → Enter
"""
import ctypes
import ctypes.wintypes
import time

user32 = ctypes.windll.user32

# Virtual key codes
VK_RETURN = 0x0D
VK_RIGHT = 0x27

# Scan codes
SC_ENTER = 0x1C
SC_RIGHT = 0x4D

# WM messages
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101

_VK_TO_SC = {VK_RETURN: SC_ENTER, VK_RIGHT: SC_RIGHT}
_EXTENDED_KEYS = {VK_RIGHT}  # Arrow keys need extended bit (bit 24)


def send_key(hwnd, vk):
    sc = _VK_TO_SC.get(vk, 0)
    extended = (1 << 24) if vk in _EXTENDED_KEYS else 0
    lparam_down = extended | (sc << 16) | 1
    lparam_up = extended | (sc << 16) | 1 | (1 << 30) | (1 << 31)
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lparam_down)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, lparam_up)


def find_isaac():
    windows = []
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if "isaac" in buf.value.lower() and "steam" not in buf.value.lower():
                    windows.append((hwnd, buf.value))
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return windows


# --- Main ---
windows = find_isaac()
if not windows:
    print("No Isaac window found!")
    exit(1)

hwnd, title = windows[0]
print(f"Found: {title} (HWND={hwnd})")

# The start sequence: Enter Enter Right Enter Enter Enter
sequence = [
    ("Enter (skip intro)",    VK_RETURN, 1.5),
    ("Enter (sikp title page)",   VK_RETURN, 1.5),
    ("Right (move to middle save file)", VK_RIGHT,  1.5),
    ("Enter (select save file)",       VK_RETURN, 1.5),
    ("Enter (continue/new run)",  VK_RETURN, 0.5),
    ("Enter (confirm character if new run)",        VK_RETURN, 0.3),
]

print("\nSending start sequence in 3 seconds...")
time.sleep(3.0)

for label, vk, delay in sequence:
    print(f"  -> {label}")
    send_key(hwnd, vk)
    time.sleep(delay)

print("\nDone!")
