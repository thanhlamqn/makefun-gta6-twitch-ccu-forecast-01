"""GTA VI Twitch CCU forecast: launch-day audience curve from comparable launches.

Model, in one paragraph: a big console launch that unlocks at midnight local
time is already live in New Zealand / Australia by 00:00 UTC, so hour 1 is a
large but fading overnight print; the audience then dips toward dawn, climbs
again as Europe wakes and the US unlocks (05:00Z east, 08:00Z west), and peaks
in the US evening before easing off late.  The comparables shipped in the case
file show exactly that shape, but its height depends strongly on how big the
launch already is: the bigger hour 1, the smaller the later peak relative to
it (a launch already at 800k has little headroom left; one at 20k can triple).
So for each forecast hour we take the distribution of log(viewers_h /
viewers_1) across comparable launches, weighting each launch by how close its
own hour-1 size is to this case's hour-1 size (Gaussian kernel on log size,
bandwidth 1.0, widened until the weights cover at least five effective
launches, so a target bigger than every comparable does not collapse onto
one) and by how similar its overnight fall into hour 1 was
(bandwidth 0.5), then blend the weighted empirical quantiles with a normal
approximation built from the weighted interquartile range.  Launches whose
hour 1 is still tiny next to their pre-release hours are simultaneous-global
unlocks, not rolling ones; if this case looks like one of those (or no
rolling comparable exists) we fall back to the unweighted distribution over
all comparables, which is much wider.  Everything is computed from the case
file at runtime; the only constants are the fallback curve used when the case
carries no usable comparable at all.

Standard library only, no network, deterministic.
"""

import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Gaussian kernel bandwidths for the similarity weights.
SIZE_BW = 1.0
DECLINE_BW = 0.5

# Fallback median log-ratios to hour 1 for hours 2..24, and a log spread,
# from the rolling launches in the practice kit, used only when the case
# carries no usable comparable at all.
FALLBACK_MEDIAN_LOG = [
    -0.128, -0.336, -0.357, -0.274, -0.238, -0.250, -0.213, -0.297,
    -0.240, -0.163, -0.081, -0.007, 0.040, 0.150, 0.243, 0.290,
    0.330, 0.488, 0.435, 0.476, 0.543, 0.597, 0.270,
]
FALLBACK_SD = 0.55


def _parse_time(text):
    """ISO-8601 UTC timestamp -> epoch seconds (fromisoformat handles +00:00)."""
    return _dt_fromiso(text.replace("Z", "+00:00")).timestamp()


def _dt_fromiso(text):
    from datetime import datetime

    return datetime.fromisoformat(text)


def _hour_index(day_start, moment):
    """Whole-hour offset of `moment` from the release day's start, 1-based."""
    return int((_parse_time(moment) - _parse_time(day_start)) // 3600) + 1


def _round2(value):
    """Round to 2 decimals, half up; whole numbers come back as ints."""
    scaled = value * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    out = whole / 100.0
    return int(out) if float(out).is_integer() else out


def _weighted_quantile(pairs, level):
    """Weighted quantile of (value, weight) pairs; values need not be sorted."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return ordered[len(ordered) // 2][0]
    target = level * total
    acc = 0.0
    for value, weight in ordered:
        acc += weight
        if acc >= target:
            return value
    return ordered[-1][0]


def _curve_from_hourly(day_start, hourly):
    """Map hour offset -> viewers for one launch's hourly rows."""
    curve = {}
    for row in hourly or []:
        try:
            viewers = row.get("viewers")
            if viewers is None or viewers <= 0:
                continue
            hour = _hour_index(day_start, row["from"])
            curve[hour] = float(viewers)
        except (KeyError, TypeError, ValueError):
            continue
    return curve


def _is_target_history(comp):
    text = (comp.get("name") or "") + " " + (comp.get("unlock") or "")
    return "Grand Theft Auto VI" in text and "Not a launch" in text


def _usable_comparables(case):
    """Comparable launches with a usable release-day curve, as (curve, info)."""
    out = []
    for comp in case.get("comparables") or []:
        if _is_target_history(comp):
            continue
        unlock = comp.get("unlock") or ""
        if "Tier: weak" in unlock:
            continue
        curve = _curve_from_hourly(comp.get("day_start"), comp.get("hourly"))
        day_hours = [h for h in curve if 1 <= h <= 24]
        if 1 not in curve or len(day_hours) < 20:
            continue
        out.append((curve, comp))
    return out


def _pre_max(curve, lo=-12, hi=0):
    vals = [v for h, v in curve.items() if lo <= h <= hi]
    return max(vals) if vals else 0.0


def _decline(curve):
    """Log fall from the last pre-release hour into hour 1; 0 when unknown."""
    if 0 in curve and 1 in curve and curve[0] > 0:
        return math.log(curve[1] / curve[0])
    return 0.0


def _looks_rolling(target_curve, p1):
    """True when hour 1 already carries a live audience (rolling midnight
    unlock): the pre-release hours reached a good fraction of hour 1."""
    return p1 >= 1000 and _pre_max(target_curve) >= 0.25 * p1


def _rolling_pool(comps):
    """Comparables that themselves look like rolling launches."""
    pool = []
    for curve, _comp in comps:
        if curve[1] >= 10000 and _pre_max(curve) >= 0.25 * curve[1]:
            pool.append((curve, _comp))
    return pool


def _hour_log_quantiles(pool, target_p1, target_decline, hour, weighted):
    """Five log-quantiles of viewers_h / viewers_1 for one hour."""
    rows = []
    for curve, _comp in pool:
        if hour not in curve:
            continue
        rows.append((curve, math.log(curve[hour] / curve[1])))
    if len(rows) < 5:
        return None
    pairs = []
    if weighted:
        # Widen the size kernel until the weights spread over at least five
        # effective launches: a target bigger than every comparable (GTA VI
        # may well be) must not collapse onto a single nearest launch.
        size_bw = SIZE_BW
        while True:
            pairs = []
            for curve, value in rows:
                size_gap = math.log(curve[1]) - math.log(target_p1)
                dec_gap = _decline(curve) - target_decline
                weight = math.exp(-(size_gap * size_gap) / (2 * size_bw * size_bw))
                weight *= math.exp(-(dec_gap * dec_gap) / (2 * DECLINE_BW * DECLINE_BW))
                pairs.append((value, weight))
            total = sum(w for _, w in pairs)
            ess = (total * total) / sum(w * w for _, w in pairs) if total > 0 else 0
            if ess >= 5 or size_bw >= 2.5:
                break
            size_bw *= 1.5
    else:
        pairs = [(value, 1.0) for _curve, value in rows]
    median = _weighted_quantile(pairs, 0.5)
    q25 = _weighted_quantile(pairs, 0.25)
    q75 = _weighted_quantile(pairs, 0.75)
    spread = max((q75 - q25) / 1.349, 0.15)
    empirical = [_weighted_quantile(pairs, level) for level in LEVELS]
    normal = [median + z * spread for z in Z]
    return [(e + n) / 2.0 for e, n in zip(empirical, normal)]


def _smooth(log_rows):
    """Three-hour moving average in log space, per quantile column."""
    hours = sorted(log_rows)
    smoothed = {}
    for pos, hour in enumerate(hours):
        neighbours = [hours[j] for j in (pos - 1, pos, pos + 1)
                      if 0 <= j < len(hours)]
        smoothed[hour] = [
            sum(log_rows[h][k] for h in neighbours) / len(neighbours)
            for k in range(5)
        ]
    return smoothed


def _fallback_log_quantiles(hour):
    median = FALLBACK_MEDIAN_LOG[hour - 2]
    return [median + z * FALLBACK_SD for z in Z]


def forecast_case(case, name):
    known = next((k for k in case.get("known", []) if k.get("hour") == 1), None)
    if known is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1.0, float(known["viewers"]))

    target_curve = _curve_from_hourly(
        case.get("day_start"), case.get("history_hourly") or []
    )
    if not target_curve:
        # Minute reads carry the same information, one point per hour at most.
        seen = {}
        for point in case.get("history") or []:
            try:
                hour = _hour_index(case["day_start"], point["at"])
                if point.get("viewers"):
                    seen[hour] = float(point["viewers"])
            except (KeyError, TypeError, ValueError):
                continue
        target_curve = seen

    comps = _usable_comparables(case)
    rolling = _rolling_pool(comps)
    if _looks_rolling(target_curve, p1) and len(rolling) >= 8:
        pool, weighted = rolling, True
    elif comps:
        pool, weighted = comps, False
    else:
        pool, weighted = [], False

    target_decline = _decline(target_curve)
    log_rows = {}
    for row in case.get("forecast", []):
        hour = int(row["hour"])
        if pool:
            got = _hour_log_quantiles(pool, p1, target_decline, hour, weighted)
            log_rows[hour] = got if got is not None else _fallback_log_quantiles(hour)
        else:
            log_rows[hour] = _fallback_log_quantiles(hour)
    log_rows = _smooth(log_rows)

    hours = []
    for row in case.get("forecast", []):
        hour = int(row["hour"])
        quantiles = []
        prev = None
        for log_q in log_rows[hour]:
            value = p1 * math.exp(log_q)
            value = min(max(value, 1.0), 1e9)
            if prev is not None and value < prev:
                value = prev
            quantiles.append(_round2(value))
            prev = quantiles[-1]
        hours.append({"hour": hour, "q": quantiles})
    hours.sort(key=lambda r: r["hour"])
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        out_path.write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
