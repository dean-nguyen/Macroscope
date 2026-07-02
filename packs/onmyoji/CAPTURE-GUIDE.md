# Onmyoji Pack — Capture Guide

Capture each image below with **Editor → Capture Region** and save it under the
**exact name** shown (the macros reference these names). Drag a *tight* box
around just the element. Capture at the resolution you'll run at.

## Shared battle templates (used by most macros)
| Save as | Screenshot of |
|---|---|
| `onmyoji_battle_ready.png` | The button that starts a fight (Challenge / 挑战 / 准备 / 开始战斗) |
| `onmyoji_challenge_again.png` | The **replay** button after a win (再次挑战 / Again) |
| `onmyoji_victory.png` | A stable element on the **victory / results** screen (胜利) |
| `onmyoji_reward_confirm.png` | The tap-to-continue / confirm that dismisses rewards (确定 / 点击继续) |

## Stop-condition templates
| Save as | Screenshot of | Used by |
|---|---|---|
| `onmyoji_out_of_stamina.png` | The "not enough AP/勾玉/体力" popup | Soul, Exploration, Orochi, Awakening |
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

## Which macro needs which templates
- **Soul / Exploration / Orochi / Awakening:** battle_ready, challenge_again, victory, reward_confirm, out_of_stamina
- **Bounty / Demon:** battle_ready, challenge_again, victory, reward_confirm, no_attempts
- **Realm Raid:** realmraid_attack, realmraid_refresh, victory, reward_confirm, no_attempts
- **Daily Sign-in & Mail:** signin_claim, mail_claim, reward_confirm

## Tips
- If a macro clicks too early/late, adjust the action's `threshold` (higher = stricter)
  or the `loop_delay_ms` in the macro.
- If detection misses, re-capture the template a bit larger / with more unique detail.
- These macros repeat the **battle** — open the activity screen first, or add
  your own navigation clicks at the top of the macro.
