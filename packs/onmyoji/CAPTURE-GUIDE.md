# Onmyoji Pack — Capture Guide

Capture each image with the **Guided Capture** wizard (Images → Guided capture…),
which walks this list and saves each file under the exact name the macros expect.
Drag a *tight* box around just the element, **at the window size you will bot at**.

Wording below is from the **English Steam client**, checked against a live game.

## The one rule that matters

**Crop distinctive content — words, banners, icons. Never a bare button.**

Onmyoji reuses a single button chrome across the whole UI. A capture of the
plain **OK** button was measured scoring **0.91 against the Realm Raid Refresh
button** — a completely different control — because two characters of text
cannot outweigh a box of flat orange fill. A macro built on such a template
clicks the wrong thing confidently.

That is why popups here are handled in two parts: a *distinctive* template
detects the popup, and the OK is then pressed by position (the dialog is modal
and centred, so its OK is always at the same fraction of the window).

## Capture these now (they are always reachable)

| Save as | Where it is | Notes |
|---|---|---|
| `onmyoji_battle_ready.png` | Any activity screen → the diamond **Challenge** | Crop the word only. Leave out the ticket number under it — it changes. |
| `onmyoji_realmraid_attack.png` | Realm Raid → click a target → **Attack** | Only exists *after* a target is selected. |
| `onmyoji_realmraid_refresh.png` | Realm Raid → **Refresh**, bottom right | |
| `onmyoji_mail_claim.png` | Mailbox → System Mail → **Read All** | Reading is what grants attachments here, so this *is* claim-all. |
| `onmyoji_reward_confirm.png` | Finish any fight → **Tap to continue** at the bottom | Needs one real battle. Every farming macro relies on it. |

## Sign-in is event-dependent

`onmyoji_signin_claim.png` is the one capture that will not stay valid.

Onmyoji has **no permanent daily sign-in screen**. The **Bonus** lantern is not
it — that panel just lists active buff timers (Evo zones, EXP bonus, …). The
check-in lives inside whichever event is currently running (**Event → Exciting
Events**), so the button's look and position change when the event rotates.

Capture it from the event that is live, and expect to re-capture it — the
**Daily Sign-in** macro is only as current as that screenshot.

## Capture these when you happen to see them

These states cannot be summoned on demand — keep the wizard handy and grab them
the first time each appears. Until then those checks simply never match; the
macros still run (the log lists what is missing at the start of every run).

| Save as | Appears when | Crop what | What the macro does |
|---|---|---|---|
| `onmyoji_captcha.png` | A verification screen appears | its distinctive artwork/text | **STOPS the bot.** The key anti-ban guard — until captured, it protects nothing. |
| `onmyoji_out_of_stamina.png` | You run out of AP | the message text | Stops the AP farms |
| `onmyoji_no_attempts.png` | A daily limit is spent | the message text | Stops Bounty / Realm Raid / Demon |
| `onmyoji_inventory_full.png` | Storage fills up | the message text | Stops so you can clear space |
| `onmyoji_level_up.png` | A shikigami levels up | the **banner/title**, not the OK | OK pressed by position |
| `onmyoji_defeat.png` | You lose a fight | the **Defeat banner**, not the OK | OK pressed by position |
| `onmyoji_reconnect_retry.png` | The network drops | the retry button **with its message text** | Auto-clicked to recover |

## Optional

| Save as | Why you might not need it |
|---|---|
| `onmyoji_challenge_again.png` | The English Steam client has **no** "challenge again" button — it returns to the activity screen, where `battle_ready` is used instead. Capture only if your client differs. |

## Which macro needs which

- **Soul / Exploration / Orochi / Awakening:** battle_ready, reward_confirm, out_of_stamina + captcha, inventory_full, level_up, defeat, reconnect_retry
- **Bounty / Demon:** the same, but `no_attempts` instead of `out_of_stamina`
- **Realm Raid:** realmraid_attack, realmraid_refresh, reward_confirm, no_attempts + the resilience set
- **Claim Mail:** mail_claim, reward_confirm
- **Daily Sign-in:** signin_claim, reward_confirm

## Tips

- **Templates now survive a window resize.** The matcher discovers the scale
  factor on its own and caches it, so a template captured at 2840×1600 still
  matches at other sizes. Capturing at your real size is still the sharpest.
- If a macro clicks too early or grabs the wrong thing, raise its `threshold`.
  These are raw correlation: the shipped macros use `0.80` for anything they click
  and `0.70` for stop-guards. On a live window a template that is present scores
  `~0.92` and absent ones reach `~0.47`, so there is room to tighten.
- If detection misses, re-capture the template slightly larger, with more
  distinctive detail inside the box.
- These macros repeat the **battle** — open the activity screen first, or add
  your own navigation clicks at the top.
- Navigation clicks should use `xp`/`yp` (fractions of the window) rather than
  `x`/`y` pixels, so they survive a resize too.
