"""Tests for choosing which window a macro drives.

These exist because of a measured incident, not a hypothetical one. A macro with
`"target_window": "Onmyoji"` resolved to a browser tab titled
"(176) Onmyoji - 預選賽 2200-3000 2026.08.06 Grand Zenith Duel - YouTube" while the
game window "陰陽師Onmyoji" was open, and posted a click into the browser. A
substring is not an identity.
"""

import pytest

from engine import background_input as bi
from engine.macro_engine import MacroEngine

pytestmark = pytest.mark.unit


# The real incident: the game, plus a browser tab that merely mentions it.
GAME = (721146, "陰陽師Onmyoji", "Win32Window")
GAME2 = (592852, "陰陽師Onmyoji", "Win32Window")
YOUTUBE = (462176, "(176) Onmyoji - 預選賽 2200–3000 Grand Zenith Duel - YouTube",
           "Chrome_WidgetWin_1")
EXPLORER = (131588, "Onmyoji", "CabinetWClass")
LAUNCHER = (222222, "Onmyoji Launcher", "Win32Window")
SEARCH_TAB = (333333, "Onmyoji - Google Search - Google Chrome", "Chrome_WidgetWin_1")
WIKI_TAB = (444444, "Onmyoji Wiki | Fandom - Google Chrome", "Chrome_WidgetWin_1")


def _fake_windows(monkeypatch, windows):
    """Present *windows* to the finder in the given z-order."""
    def enum(cb, extra):
        for hwnd, _title, _cls in windows:
            cb(hwnd, extra)

    titles = {h: t for h, t, _ in windows}
    classes = {h: c for h, _, c in windows}
    monkeypatch.setattr(bi.win32gui, "EnumWindows", enum)
    monkeypatch.setattr(bi.win32gui, "IsWindowVisible", lambda h: True)
    monkeypatch.setattr(bi.win32gui, "GetWindowText", lambda h: titles[h])
    monkeypatch.setattr(bi.win32gui, "GetClassName", lambda h: classes[h])


# ── ranking ───────────────────────────────────────────────────────────────────

def test_the_browser_tab_does_not_win_just_by_being_first(monkeypatch):
    """The incident, exactly: the tab came first in z-order and was chosen."""
    _fake_windows(monkeypatch, [YOUTUBE, GAME])
    assert bi.find_window("Onmyoji") == GAME[0]


def test_an_exactly_named_folder_still_wins_and_the_class_is_the_answer(monkeypatch):
    """A known limit, pinned rather than papered over.

    A folder titled exactly "Onmyoji" outranks a game titled "陰陽師Onmyoji", because an
    exact title genuinely is the stronger signal and nothing in a title or a window
    class says which of the two is the application. Ranking is only a fallback for a
    hand-typed name — `target_class`, which the window picker records, is what settles
    it, and this test shows that it does.
    """
    _fake_windows(monkeypatch, [YOUTUBE, EXPLORER, GAME])
    assert bi.find_window("Onmyoji") == EXPLORER[0]
    assert bi.find_window("Onmyoji", "Win32Window") == GAME[0]


def test_an_exact_title_beats_a_longer_one_among_equals(monkeypatch):
    exact = (1, "Onmyoji", "Win32Window")
    _fake_windows(monkeypatch, [GAME, exact])
    assert bi.find_window("Onmyoji") == exact[0]


def test_there_is_no_begins_with_tier(monkeypatch):
    """It looks obvious and it inverts the real case: the game's title only
    *contains* the pattern, so a prefix tier promotes a launcher above the game."""
    _fake_windows(monkeypatch, [LAUNCHER, GAME])
    assert bi.find_window("Onmyoji") == GAME[0]


@pytest.mark.parametrize("other", [YOUTUBE, SEARCH_TAB, WIKI_TAB, LAUNCHER])
def test_nothing_that_merely_mentions_the_game_outranks_it(monkeypatch, other):
    """Each of these was measured beating the game window before this ranking."""
    _fake_windows(monkeypatch, [other, GAME])
    assert bi.find_window("Onmyoji") == GAME[0], other[1]


def test_a_browser_is_still_reachable_when_it_is_the_only_match(monkeypatch):
    """Deprioritised, never excluded — the engine supports driving Electron apps, and
    Electron is Chrome_WidgetWin_1."""
    _fake_windows(monkeypatch, [SEARCH_TAB])
    assert bi.find_window("Onmyoji") == SEARCH_TAB[0]


@pytest.mark.parametrize("distraction", [
    (1, "slack rollout notes.txt - Notepad", "Notepad"),
    (2, "slack — Windows PowerShell", "ConsoleWindowClass"),
])
def test_an_electron_app_is_not_demoted_out_of_its_own_name(monkeypatch, distraction):
    """Demoting the whole class outright was measured picking a Notepad file called
    "slack rollout notes.txt" over Slack itself. An Electron app's window is titled
    just "Slack"; a browser tab is always decorated. So only a decorated title is
    demoted, and Electron is Chrome_WidgetWin_1 — a supported target."""
    slack = (99, "Slack", "Chrome_WidgetWin_1")
    _fake_windows(monkeypatch, [distraction, slack])
    assert bi.find_window("slack") == slack[0]


def test_matching_is_case_insensitive(monkeypatch):
    _fake_windows(monkeypatch, [GAME])
    assert bi.find_window("onmyoji") == GAME[0]
    assert bi.find_window("ONMYOJI") == GAME[0]


def test_equal_candidates_keep_their_z_order(monkeypatch):
    """Two instances of the same game: the topmost is still the right answer."""
    _fake_windows(monkeypatch, [GAME2, GAME])
    assert [h for h, _ in bi.find_all_windows("Onmyoji")] == [GAME2[0], GAME[0]]

    _fake_windows(monkeypatch, [GAME, GAME2])
    assert [h for h, _ in bi.find_all_windows("Onmyoji")] == [GAME[0], GAME2[0]]


def test_no_match_returns_nothing(monkeypatch):
    _fake_windows(monkeypatch, [YOUTUBE])
    assert bi.find_window("Notepad") is None
    assert bi.find_all_windows("Notepad") == []


# ── the class filter ──────────────────────────────────────────────────────────

def test_the_class_excludes_a_window_that_is_not_the_application(monkeypatch):
    """The reliable signal, recorded by the window picker: a browser is not the
    game whatever its title says."""
    _fake_windows(monkeypatch, [YOUTUBE, EXPLORER, GAME])
    assert bi.find_window("Onmyoji", "Win32Window") == GAME[0]
    assert [h for h, _ in bi.find_all_windows("Onmyoji", "Win32Window")] == [GAME[0]]


def test_a_class_that_no_longer_exists_does_not_break_the_search(monkeypatch):
    """An application that changes its window class in an update must not silently
    stop being found — picking the wrong window is the failure worth preventing."""
    _fake_windows(monkeypatch, [YOUTUBE, GAME])
    assert bi.find_window("Onmyoji", "ClassFromAnOldVersion") == GAME[0]


def test_window_class_of_survives_a_dead_handle(monkeypatch):
    monkeypatch.setattr(bi.win32gui, "GetClassName",
                        lambda h: (_ for _ in ()).throw(Exception("dead")))
    assert bi.window_class_of(1234) == ""


# ── what the engine does with it ──────────────────────────────────────────────

def test_the_engine_prefers_the_game_over_a_tab_that_mentions_it(monkeypatch):
    _fake_windows(monkeypatch, [YOUTUBE, GAME])
    monkeypatch.setattr(bi.win32gui, "IsWindow", lambda h: True)
    engine = MacroEngine(log_fn=lambda m: None)

    assert engine._resolve_hwnd({"target_window": "Onmyoji"}) == GAME[0]


def test_the_engine_passes_the_class_through(monkeypatch):
    """Ranking is a fallback for a hand-typed title; the class is the reliable answer.
    Here it is the only thing that separates the game from a launcher of the same
    class... which it does not — so use a case where it does: two applications whose
    titles are equally uninformative."""
    other_app = (55555, "Onmyoji", "SomeOtherApp")
    _fake_windows(monkeypatch, [other_app, GAME])
    monkeypatch.setattr(bi.win32gui, "IsWindow", lambda h: True)
    engine = MacroEngine(log_fn=lambda m: None)

    # On title alone the shorter, exact one wins.
    assert engine._resolve_hwnd({"target_window": "Onmyoji"}) == other_app[0]
    # With the class recorded by the picker, only the game is a candidate.
    assert engine._resolve_hwnd({"target_window": "Onmyoji",
                                 "target_class": "Win32Window"}) == GAME[0]


def test_an_ambiguous_match_names_every_candidate_and_its_class(monkeypatch):
    """A log line saying only "using topmost" does not tell the user that their
    browser was chosen. It has to name what it picked and what it passed over."""
    _fake_windows(monkeypatch, [YOUTUBE, GAME])
    monkeypatch.setattr(bi.win32gui, "IsWindow", lambda h: True)
    logged = []
    engine = MacroEngine(log_fn=logged.append)

    engine._resolve_hwnd({"target_window": "Onmyoji"})

    line = " ".join(logged)
    assert "2 windows match" in line
    assert "Win32Window" in line and "Chrome_WidgetWin_1" in line
    assert "YouTube" in line
    assert "target_class" in line, "the log must say how to fix it"


def test_the_editor_resolves_with_the_class_it_recorded(monkeypatch):
    """Or testing a macro from the editor drives a different window than running the
    saved macro does — the picker records the class and then the editor ignored it."""
    from types import SimpleNamespace

    from gui.editor import MacroEditor

    _fake_windows(monkeypatch, [EXPLORER, GAME])
    stub = SimpleNamespace(
        _bg_var=SimpleNamespace(get=lambda: True),
        _target_hwnd=None,
        _target_class="Win32Window",
        _target_var=SimpleNamespace(get=lambda: "Onmyoji"),
    )
    assert MacroEditor._resolve_target_hwnd(stub) == GAME[0]

    stub._target_class = None
    assert MacroEditor._resolve_target_hwnd(stub) == EXPLORER[0]


def test_a_live_saved_hwnd_still_wins(monkeypatch):
    """The picker's exact handle is the strongest signal while it is valid."""
    _fake_windows(monkeypatch, [YOUTUBE, GAME])
    monkeypatch.setattr(bi.win32gui, "IsWindow", lambda h: True)
    engine = MacroEngine(log_fn=lambda m: None)

    assert engine._resolve_hwnd({"target_window": "Onmyoji",
                                 "target_hwnd": GAME2[0]}) == GAME2[0]


def test_no_targeting_at_all_resolves_to_nothing():
    engine = MacroEngine(log_fn=lambda m: None)
    assert engine._resolve_hwnd({}) is None
    assert engine._resolve_hwnd({"target_window": "   "}) is None
