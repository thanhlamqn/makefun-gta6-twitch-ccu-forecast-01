# GTA VI Twitch CCU forecast — gta6-twitch-ccu-forecast-01

[![make.fun](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/thanhlamqn/makefun-gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/thanhlamqn/makefun-gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

Entry for the [GTA VI Twitch viewer forecast bounty](https://make.fun/bounty/gta6-twitch-ccu-forecast-01):
forecast, hour by hour, how many people watch Grand Theft Auto VI live on
Twitch over the 24 UTC hours of its release day, 2026-11-19, from everything
recorded up to the end of its first hour, as five quantiles an hour.

## The model

`main.py` (Python 3, standard library only, no network, deterministic) reads
one case file and writes one forecast. It models the launch-day audience
curve from the comparable launches shipped in the case file:

- A big console launch that unlocks at midnight local time is already live in
  New Zealand / Australia by 00:00 UTC, so hour 1 is a large but fading
  overnight print. The audience dips toward dawn, climbs as Europe wakes and
  the US unlocks (05:00Z east, 08:00Z west), and peaks in the US evening
  before easing off late.
- The height of that curve depends strongly on how big the launch already
  is: the bigger hour 1, the smaller the later peak relative to it (a launch
  already at 800k has little headroom left; one at 20k can triple). For each
  forecast hour the program takes the distribution of log(viewers_h /
  viewers_1) across comparable launches, weighting each launch by how close
  its own hour-1 size is to this case's (Gaussian kernel on log size,
  widened until the weights cover at least five effective launches) and by
  how similar its overnight fall into hour 1 was, then blends the weighted
  empirical quantiles with a normal approximation from the weighted
  interquartile range.
- Launches whose hour 1 is still tiny next to their pre-release hours are
  simultaneous-global unlocks, not rolling ones. If the case looks like one
  of those (or no rolling comparable exists), the program falls back to the
  unweighted distribution over all comparables, which is much wider. The
  GTA VI category's own pre-release history and weak-tier (free-to-play)
  launches are excluded from the comparable pool.

## Validation

The kit holds no practice answers locally (the scorer and reference data stay
on the server), so the program was validated by leave-one-out cross-validation
on the comparables themselves: each of the 27 rolling comparable launches was
rebuilt as a pseudo-case (its own hour-1 print plus the other 37 comparables)
and the shipped `main.py` was run end to end on it, scoring the documented
pinball loss on the log scale against that launch's real hours 2–24:

| | mean pinball loss | typical miss | 90% coverage |
|---|---|---|---|
| This entry | **0.266** | 50.2% | 0.878 |
| House persistence baseline | 0.356 | — | — |

On the four practice cases the program runs in ~0.07 s per case, writes
valid output (23 rows, hours 2–24, five non-decreasing quantiles each), and is
byte-identical across repeated runs. Its predicted evening peaks scale with
hour-1 size as the comparables say they should: ~3.2× hour 1 for the smallest
practice case (23k viewers in hour 1), ~1.3× for the largest (270k).

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## License

MIT — see [LICENSE](LICENSE).

---

Built for [make.fun](https://make.fun/r/3ky049kf) — try it with my referral link: https://make.fun/r/3ky049kf
