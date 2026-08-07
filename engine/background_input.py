"""
Background input — send mouse/keyboard events directly to a target window
via Win32 PostMessage, without moving the real system cursor or stealing
keyboard focus from the user.

Coordinates are in CLIENT space (relative to the target window's top-left
inner corner).  The caller is responsible for converting if needed.

Limitations
-----------
* Does not work with games that use DirectInput / raw-input exclusively.
* WM_CHAR covers printable ASCII; use WM_KEYDOWN for special keys.
* Some apps ignore posted messages; test with your specific target.
"""

import time
from typing import List, Optional, Tuple

import win32api
import win32con
import win32gui


# ── window helpers ────────────────────────────────────────────────────────────

def find_window(title_pattern: str, window_class: Optional[str] = None) -> Optional[int]:
    """
    Return the HWND of the best visible window matching `title_pattern`
    (case-insensitive substring), or None.

    "Best" is defined by find_all_windows, which ranks candidates rather than
    taking whatever EnumWindows happens to reach first.
    """
    matches = find_all_windows(title_pattern, window_class)
    return matches[0][0] if matches else None


def window_class_of(hwnd: int) -> str:
    """The window's class name, or "" if it cannot be read."""
    try:
        return win32gui.GetClassName(hwnd) or ""
    except Exception:
        return ""


# Window classes that host content the user opened — a tab, a document, a folder —
# rather than being an application whose name is its title.
#
# Demoted only when the title is **decorated**, i.e. not exactly the pattern. That
# distinction is what keeps the rule from trading one wrong window for another: a
# browser tab is always decorated ("… - YouTube", "… - Google Chrome"), while an
# Electron app's window is titled just "Slack". Demoting the whole class outright was
# measured picking a Notepad file called "slack rollout notes.txt" over Slack itself,
# and Electron is Chrome_WidgetWin_1, which CLAUDE.md lists as a supported target.
#
# Never excluded, only reordered: a window of one of these classes that is the only
# match is still returned.
_TITLE_HOSTING_CLASSES = frozenset({
    "Chrome_WidgetWin_1",           # Chrome, Edge, Electron
    "Chrome_WidgetWin_0",
    "MozillaWindowClass",           # Firefox
    "CabinetWClass",                # File Explorer
    "ApplicationFrameWindow",       # UWP host
    "Windows.UI.Core.CoreWindow",
    "Progman", "WorkerW",           # the desktop itself
})


def _match_rank(hwnd: int, title: str, pattern: str) -> tuple:
    """Sort key for one candidate window. Lower is better.

    A bare substring search is not enough to identify an application: the title
    "Onmyoji" also matches a browser tab called
    "(176) Onmyoji - 預選賽 … - YouTube", and a macro that resolved to that tab posted
    its clicks into the browser. Measured, not hypothetical.

    Ranked by how much of the window's identity the pattern accounts for: not a
    decorated tab or folder first, then an exact title, then the shortest title. A
    window whose name *is* the application carries little else, while a tab decorates
    its title with content and the app's own name.

    There is deliberately **no** "begins with the pattern" tier. It looks obvious and
    it inverts real cases: the game's own title is "陰陽師Onmyoji", which only
    *contains* the pattern, so a prefix tier promoted "Onmyoji Launcher", "Onmyoji -
    Google Search - Google Chrome" and "Onmyoji Wiki | Fandom" above the game — the
    same defect this ranking exists to fix, wearing a different title.

    **This cannot always be right.** A folder named exactly "Onmyoji" still outranks a
    game titled "陰陽師Onmyoji", because an exact title is genuinely the stronger
    signal and nothing in a title or a class says which window is the application.
    Ranking is only a fallback for a hand-typed name; `window_class`, which the window
    picker records, is the reliable answer.
    """
    exact = title.lower() == pattern
    decorated_content = (not exact) and window_class_of(hwnd) in _TITLE_HOSTING_CLASSES
    return (1 if decorated_content else 0,
            0 if exact else 1,
            len(title))


def find_all_windows(
    title_pattern: str,
    window_class: Optional[str] = None,
) -> List[Tuple[int, str]]:
    """
    Return visible windows matching `title_pattern` (case-insensitive substring),
    best first. Returns [(hwnd, title), …].

    When `window_class` is given, windows of another class are excluded — unless
    that leaves nothing, in which case the filter is dropped. An application that
    changes its window class in an update should not silently stop being found;
    picking a wrong window is the failure worth preventing, and the caller logs
    which one it took.
    """
    pattern = title_pattern.lower()
    result = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if pattern in t.lower():
                result.append((hwnd, t))

    win32gui.EnumWindows(_cb, None)

    if window_class:
        same_class = [m for m in result if window_class_of(m[0]) == window_class]
        if same_class:
            result = same_class

    # sorted() is stable, so windows of equal rank keep their z-order.
    return sorted(result, key=lambda m: _match_rank(m[0], m[1], pattern))


def is_window_valid(hwnd: int) -> bool:
    """Check if a window handle is still valid and visible."""
    try:
        return bool(win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd))
    except Exception:
        return False


def list_windows() -> List[Tuple[int, str]]:
    """Return [(hwnd, title), …] for all visible top-level windows."""
    windows = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if t:
                windows.append((hwnd, t))

    win32gui.EnumWindows(_cb, None)
    return sorted(windows, key=lambda x: x[1].lower())


def screen_to_client(hwnd: int, x: int, y: int) -> Tuple[int, int]:
    """Convert absolute screen coords to window client coords."""
    return win32gui.ScreenToClient(hwnd, (x, y))


# ── low-level helpers ─────────────────────────────────────────────────────────

def _lparam(x: int, y: int) -> int:
    return (y & 0xFFFF) << 16 | (x & 0xFFFF)


# Virtual-key map for common key names (mirrors pyautogui naming)
_VK_MAP = {
    "enter": win32con.VK_RETURN,
    "return": win32con.VK_RETURN,
    "tab": win32con.VK_TAB,
    "backspace": win32con.VK_BACK,
    "delete": win32con.VK_DELETE,
    "del": win32con.VK_DELETE,
    "esc": win32con.VK_ESCAPE,
    "escape": win32con.VK_ESCAPE,
    "space": win32con.VK_SPACE,
    "up": win32con.VK_UP,
    "down": win32con.VK_DOWN,
    "left": win32con.VK_LEFT,
    "right": win32con.VK_RIGHT,
    "home": win32con.VK_HOME,
    "end": win32con.VK_END,
    "pageup": win32con.VK_PRIOR,
    "pagedown": win32con.VK_NEXT,
    "insert": win32con.VK_INSERT,
    "ctrl": win32con.VK_CONTROL,
    "alt": win32con.VK_MENU,
    "shift": win32con.VK_SHIFT,
    "win": win32con.VK_LWIN,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},  # F1-F12
}


def _vk(key: str) -> int:
    k = key.lower()
    if k in _VK_MAP:
        return _VK_MAP[k]
    if len(k) == 1:
        return win32api.VkKeyScan(k) & 0xFF
    raise ValueError(f"Unknown key: '{key}'")


# ── public API ────────────────────────────────────────────────────────────────

def post_click(hwnd: int, x: int, y: int, button: str = "left") -> None:
    lp = _lparam(x, y)
    if button == "left":
        down, up = win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP
        wp = win32con.MK_LBUTTON
    elif button == "right":
        down, up = win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP
        wp = win32con.MK_RBUTTON
    else:
        down, up = win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP
        wp = win32con.MK_MBUTTON
    win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lp)
    win32gui.PostMessage(hwnd, down, wp, lp)
    win32gui.PostMessage(hwnd, up, 0, lp)


def post_double_click(hwnd: int, x: int, y: int) -> None:
    post_click(hwnd, x, y, "left")
    time.sleep(0.05)
    post_click(hwnd, x, y, "left")


def post_right_click(hwnd: int, x: int, y: int) -> None:
    post_click(hwnd, x, y, "right")


def post_move(hwnd: int, x: int, y: int) -> None:
    win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, _lparam(x, y))


def post_scroll(hwnd: int, x: int, y: int, amount: int) -> None:
    # WM_MOUSEWHEEL uses screen coords in lParam and WHEEL_DELTA in wParam
    delta = amount * win32con.WHEEL_DELTA
    # Convert client → screen for WM_MOUSEWHEEL lParam
    sx, sy = win32gui.ClientToScreen(hwnd, (x, y))
    wp = (delta & 0xFFFF) << 16
    lp = _lparam(sx, sy)
    win32gui.PostMessage(hwnd, win32con.WM_MOUSEWHEEL, wp, lp)


def post_key(hwnd: int, keys: List[str]) -> None:
    """Press a key or key combination (e.g. ['ctrl','c'])."""
    modifiers = [k for k in keys if k.lower() in ("ctrl", "alt", "shift", "win")]
    main_keys = [k for k in keys if k.lower() not in ("ctrl", "alt", "shift", "win")]

    # key-down modifiers
    for mod in modifiers:
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, _vk(mod), 0)

    # main key(s)
    for k in (main_keys if main_keys else modifiers[-1:]):
        vk = _vk(k)
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, 0)
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk, 0)

    # key-up modifiers (reverse order)
    for mod in reversed(modifiers):
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, _vk(mod), 0)


def post_type(hwnd: int, text: str, interval: float = 0.02) -> None:
    """Type a string using WM_CHAR for each character."""
    for ch in text:
        win32gui.PostMessage(hwnd, win32con.WM_CHAR, ord(ch), 0)
        if interval > 0:
            time.sleep(interval)


def post_drag(hwnd: int, x: int, y: int, x2: int, y2: int,
              duration: float = 0.2, button: str = "left") -> None:
    lp_start = _lparam(x, y)
    lp_end = _lparam(x2, y2)
    if button == "left":
        down, up, mk = win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON
    else:
        down, up, mk = win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP, win32con.MK_RBUTTON

    steps = max(int(duration / 0.02), 2)
    win32gui.PostMessage(hwnd, down, mk, lp_start)
    for i in range(steps + 1):
        t = i / steps
        ix = int(x + (x2 - x) * t)
        iy = int(y + (y2 - y) * t)
        win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, mk, _lparam(ix, iy))
        time.sleep(duration / steps)
    win32gui.PostMessage(hwnd, up, 0, lp_end)
