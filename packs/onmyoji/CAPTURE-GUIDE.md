# Onmyoji Pack — Capture Guide

Capture each image with the **Guided Capture** wizard (Images → Guided capture…),
which walks this list and saves each file under the exact name the macros expect.
Drag a *tight* box around just the element, **at the window size you will bot at**.

Wording below is from the **English Steam client**, checked against a live game.

## If you run two clients, give them the same graphics setting

Measured on two live windows showing the same guild panel: the second rendered about
35% softer, and that alone took a marker template from **1.000** on one client to
**0.697** on the other — below what a macro needs. Same coordinates, same content, and
neither brightness nor the one-pixel size difference explained it.

Capturing a bigger crop does not help; it makes it worse, because the softness is the
whole panel. Either match the clients' in-game graphics settings, or capture a separate
set of templates per client and point each account's macro at its own.

`python tools/match_report.py --title …` names the window it scored — run it against
each client when one account works and the other does not.

## The one rule that matters

**Crop distinctive content — words, banners, icons. Never a bare button.**

Onmyoji reuses a single button chrome across the whole UI. A capture of the plain
**OK** button was measured scoring **0.91 against the Realm Raid Refresh button** —
a completely different control — because two characters of text cannot outweigh a
box of flat orange fill. A macro built on such a template clicks the wrong thing
confidently.

The wizard now scores each crop as you take it and says so: it refuses a
featureless one outright, and warns when a crop is not unique on the screen it came
from or scores too close to a template you already have.

## Capture these now — the macros do not work without them

| Save as | Where it is | Notes |
|---|---|---|
| `onmyoji_realmraid_attack.png` | Realm Raid → click a target → **Attack** | Only exists *after* a target is selected. Verified live at 0.98. |
| `onmyoji_realmraid_refresh.png` | Realm Raid → **Refresh**, bottom right | Also the "am I on the Individual list" marker — it exists nowhere else. |
| `onmyoji_realmraid_guild_progress.png` | Realm Raid → **Guild** tab → the red **Raid Progress** banner, left panel | The Guild list has no Refresh, so this is its equivalent marker. |
| `onmyoji_dialog_ok.png` | Realm Raid → **Refresh** → the **OK** on "Raid log progress will be reset…" | The standard confirm scroll, reused across the game. Without it the macro presses Refresh forever and never refreshes anything. |
| `onmyoji_reward_confirm.png` | Finish any fight → **Tap to continue** at the bottom | Needs one real battle. Every macro clears every result screen with it, on a win and a loss alike. |
| `onmyoji_souls_challenge.png` | Souls → **Sougenbi** → **Foolery** → the **Challenge** button, bottom right | **Ships with the pack.** Crop the **word**, not the diamond around it and not the `x1` cost under it: the diamond is shared chrome and the number changes. |
| `onmyoji_souls_foolery.png` | The same screen → the **Foolery** label in the sidebar, **selected** | **Ships with the pack.** The 'am I on the right gate' marker. Capture it *selected* — see below. |

## Capture these when you happen to see them

These states cannot be summoned on demand — keep the wizard handy and grab them the
first time each appears. Until then those checks simply never match; the macros
still run, they just do not stop for the reason named. The log lists what is
missing at the start of every run.

| Save as | Appears when | Crop what | What the macro does |
|---|---|---|---|
| `onmyoji_captcha.png` | A verification screen appears | its distinctive artwork/text | **STOPS the macro.** Until captured it protects nothing — but the engine's stall guard stops a macro that clicks without recognising anything for five minutes, so this is no longer the only backstop. |
| `onmyoji_no_attempts.png` | Realm Raid tickets run out | the message text | Stops Realm Raid (Individual) |
| `onmyoji_no_stamina.png` | You press Challenge on a Souls gate with nothing left to pay with | the message text | Stops the Souls macro |
| `onmyoji_guild_no_wins.png` | Guild raid daily wins run out — **may never appear** | the message text | Nothing depends on it. After 09:00 Vietnam time the guild raid stops *counting* wins instead of blocking: the crest reads 'Raided', the counter stops moving, and you keep attacking until nothing is left. So the Guild macro ends when no member has offered an Attack button for two minutes, not on this popup. The `Win(s): n/6` on that tab is wins **remaining**, not used. |
| `onmyoji_inventory_full.png` | Storage fills up | the message text | Stops so you can clear space |
| `onmyoji_level_up.png` | A shikigami levels up | the **banner/title**, not the OK | Makes the macro look for something it can dismiss |
| `onmyoji_defeat.png` | You lose a fight | the **Failed** banner, not the panel below | Same — the loss is then cleared like any other result |
| `onmyoji_reconnect_retry.png` | The network drops | the retry button **with its message text** | Auto-clicked to recover |
| `onmyoji_wanted_quest_decline.png` | Another player invites you to a Wanted Quest | the **decline / close / X**, with enough of the popup around it to be distinctive | Clicked, so the raid carries on. See the warning below. |

### The invitation: crop the decline, never the accept

An invitation can arrive over any screen. Accepting one takes the client into a
different activity, and these macros do not navigate — they would be left clicking
raid coordinates at a bounty screen until the stall guard stops them.

The macro clicks **exactly what this template shows**. Crop the accept button by
mistake and it will accept every invitation that arrives. That is also why the
invitation is not cleared by the generic dismiss path the level-up and defeat
screens use: that path presses the game's standard confirm scroll, and on an
invitation the standard confirm *is* accept.

Until it is captured, an invitation that covers the target list simply stalls the
macro — it clicks nothing — and one that leaves the list visible may take a grid
click meant for a target.

### The Foolery marker must be captured *selected*

Sougenbi has three gates — Greed, Anger and Foolery — and **all three put a Challenge
button in the same place**. So a marker that matched any of them would happily farm the
wrong gate for an hour.

Unselected, "Foolery" is pale text on the same parchment as its neighbours. Selected, it
sits on a red brush stroke. Only the selected state distinguishes *which* gate you are
on, which is why the macro's screen check uses it and why it has to be captured with
Foolery highlighted.

The same crop doubles as "am I still on the Souls screen at all", so a fight, a loading
screen or an unanswered dialog all read as "not on the gate" and nothing is pressed.

### Do not capture a "Challenge Again"

The English client shows none after a win — it returns to the activity screen. It
shows one after a **loss**, inside the "Get stronger via:" panel. Pointing a raid
macro at that button means retrying the fight you just lost, which spends another
attempt on a target you cannot beat and will burn the daily allowance.

For the same reason the macros never dismiss a screen by pressing a *position*: the
middle of the defeat screen is that panel. They click only what they can see.

## Which macro needs which

- **Realm Raid (Individual):** realmraid_attack, realmraid_refresh, dialog_ok,
  reward_confirm, no_attempts + captcha, inventory_full, level_up, defeat,
  reconnect_retry
- **Realm Raid (Guild):** realmraid_attack, realmraid_guild_progress,
  realmraid_refresh (to find the tab from the Individual list), reward_confirm,
  guild_no_wins + the same resilience set
- **Souls (Sougenbi, Foolery):** souls_challenge, souls_foolery, reward_confirm,
  no_stamina + the same resilience set. Two templates and one button — it needs less
  than either raid because the screen gives it less to get wrong.

The "resilience set" is captcha, inventory_full, level_up, defeat, reconnect_retry
and wanted_quest_decline — every one of them opportunistic, and every one a
*stop-guard or an interruption*. Until they exist the macros run; they just do not
stop, or clear, for the reason named.

## Tips

- **Templates survive a window resize.** The matcher discovers the scale factor on
  its own and caches it, so a template captured at 2840×1600 still matches at other
  sizes — verified live at 0.44×. Capturing at your real size is still sharpest, and
  it makes the first few ticks of a run faster.
- **`python tools/match_report.py --title Onmyoji`** scores every template you have
  against the window as it is right now. A template whose element is on screen
  scores ~0.92–0.99; absent ones reach about 0.47. If everything you own scores in
  the 0.40s, nothing is matching.
