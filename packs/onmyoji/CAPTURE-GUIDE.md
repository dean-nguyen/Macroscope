# Onmyoji Pack — Capture Guide

Capture each image below with **Editor → Capture Region** (or the **Guided
Capture** wizard, which walks this list for you) and save it under the **exact
name** shown. Drag a *tight* box around just the element. Capture at the
resolution you'll run at.

## Core battle loop
| Save as | Screenshot of |
|---|---|
| `onmyoji_battle_ready.png` | The button that starts a fight (Challenge / 挑战 / 准备 / 开始战斗) |
| `onmyoji_challenge_again.png` | The **replay** button after a win (再次挑战 / Again) |
| `onmyoji_reward_confirm.png` | The tap-to-continue / confirm that dismisses the results & rewards (确定 / 点击继续) |

## Stop conditions
| Save as | Screenshot of | Used by |
|---|---|---|
| `onmyoji_out_of_stamina.png` | The "not enough AP / 勾玉 / 体力" popup | Soul, Exploration, Orochi, Awakening |
| `onmyoji_no_attempts.png` | The "no attempts / 次数已用完" state | Bounty, Realm Raid, Demon |

## Realm Raid extras
| Save as | Screenshot of |
|---|---|
| `onmyoji_realmraid_attack.png` | The **Attack** button on a raid target |
| `onmyoji_realmraid_refresh.png` | The **Refresh** targets button |

## Daily claim
| Save as | Screenshot of |
|---|---|
| `onmyoji_signin_claim.png` | The daily sign-in **Claim** button |
| `onmyoji_mail_claim.png` | The mailbox **Claim all** button |

## Resilience / anti-ban (all farming macros check these every tick)
| Save as | Screenshot of | Behavior |
|---|---|---|
| `onmyoji_captcha.png` | The verification / CAPTCHA screen | **Bot STOPS** (never clicks through — this is the key anti-ban guard) |
| `onmyoji_reconnect_retry.png` | The reconnect / network-error **Retry** button | Auto-clicked to recover |
| `onmyoji_level_up_ok.png` | The **OK** on the shikigami level-up popup | Auto-dismissed |
| `onmyoji_inventory_full.png` | The "storage / inventory full" popup | Bot STOPS (clear space) |
| `onmyoji_defeat_ok.png` | The **OK** on the battle defeat screen | Auto-dismissed to retry |

> Tip: the CAPTCHA image is the most important one to capture well — a good
> match here is what keeps accounts safe.

## Which macro needs which templates
- **Soul / Exploration / Orochi / Awakening:** battle_ready, challenge_again, reward_confirm, out_of_stamina + all resilience templates
- **Bounty / Demon:** battle_ready, challenge_again, reward_confirm, no_attempts + all resilience templates
- **Realm Raid:** realmraid_attack, realmraid_refresh, reward_confirm, no_attempts + all resilience templates
- **Daily Sign-in & Mail:** signin_claim, mail_claim, reward_confirm

## Tips
- If a macro clicks too early/late, adjust the action's `threshold` (higher = stricter)
  or `loop_delay_ms` in the macro.
- If detection misses, re-capture the template a bit larger / with more unique detail.
- These macros repeat the **battle** — open the activity screen first, or add your
  own navigation clicks at the top of the macro.
- To make defeat **stop** instead of retry, change `onmyoji_defeat_ok`'s
  `find_and_click` into an `image_check` with `on_found: [ {"type":"stop"} ]`.
