# PRD — Set the matching constants from measurement

**Backlog:** E1.3 · **Status:** done · **Landed:** `5dcbff2`

Written after the fact, because the reasoning is worth keeping: two constants
governed every match decision in the product and neither had ever been measured.

## What was wrong

**Scores were remapped.** `_cv_match` returned `(raw + 1) / 2`, compressing every
usable value into `[0.5, 1.0]`. Zero correlation read as `0.50`. Unrelated screen
content sat near `0.70`. So `threshold=0.70` looked like "70% sure" and actually
asked for no correlation at all, and the pack's nominal `0.90` was a raw `0.80`.

**`_WGC_THRESHOLD_OFFSET` was 0.10 on no evidence.** It subtracts from every
threshold when WGC took the frame, to allow for a GDI-sourced template being matched
against a different colour pipeline. In remapped units 0.10 meant 0.20 of raw
correlation — a very large allowance for a number chosen by feel. It also still
applied now that templates are captured through WGC and matched through WGC, where
there is no cross-backend penalty at all.

Together these meant absent templates scoring `0.47` raw came close to passing a
nominal `0.60` floor. Every threshold in every macro was looser than it read.

## What was measured

Cross-backend penalty — captured one live window both ways at the same moment and
cross-scored the same regions:

| Region | Penalty (raw) | Reading |
|---|---|---|
| bottom bar | 0.046 | static — this is colour |
| right column | 0.042 | static — this is colour |
| top-left band | 0.058 | has a counter and a news ticker |
| centre | 0.36 | character animation |

A control comparing **two WGC frames 50 ms apart** reproduced most of the drift in
the animated regions on its own, which is what identifies the large numbers as
animation rather than colour. A template of an animated region is unreliable
whatever the backend.

Separation between present and absent, on a live window: present `~0.92`, absent
`~0.47`. An exact crop of the same frame scores `1.0000`.

## What changed

- Scores are raw `TM_CCOEFF_NORMED`, anticorrelation floored at 0.
- `_WGC_THRESHOLD_OFFSET` = `0.08` — roughly double the worst static measurement.
- The pack's 72 thresholds set from the separation above: `0.80` for anything
  clicked, `0.70` for stop-guards, where a false stop is the safe direction. Not
  transcribed from the old values, which were looser than they looked.

## What this incidentally proved

The per-tick frame scope is a **correctness** requirement, not only an
optimisation. The same positive control scored `0.73–0.79` when the crop and the
match used separate captures, and `1.0000` when they shared one. On an animated
screen, two captures taken milliseconds apart are not the same image — so any future
measurement on this game must hold a single frame or it is measuring animation.

## Not done

Whether a template captured through GDI and matched through WGC in *production*
behaves like this measurement. The measurement cropped both templates from live
captures; it did not use a template saved by the Guided Capture wizard and then
matched days later. The `0.08` allowance is believed sufficient, not proven so.
