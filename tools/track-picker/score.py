"""Cohort-relative scoring: every track is judged against its own batch.

There is no correct spectral balance or loudness for a genre, so rather than inventing
target numbers, spectral balance and loudness are scored by deviation from the batch
median. Only metrics with an unambiguous direction (hook immediacy, motif repetition)
use fixed thresholds.
"""
from __future__ import annotations

import numpy as np

# Weights are calibrated against measured discrimination, not intuition. Over a real
# 30-track batch, the spread each metric actually produced (range as a share of its own
# maximum) was:
#
#   hook 93%   spectral 93%   motif 80%   pulse 80%   loudness 66%
#   dynamics 38%   stereo 12%
#
# Stereo width was near-constant -- 29 of 30 tracks scored full marks -- so most of its
# budget went to metrics that separate tracks. It is kept at a low weight as a guard: a
# genuinely mono or absurdly wide track should still lose something.
#
# These are tuned to one generator's output. On different material, re-measure: the
# report prints each metric's spread so you can see whether it is discriminating.
WEIGHTS = {
    "hook": 24,        # does it grab within the first 3-5 seconds
    "motif": 20,       # does a memorable figure come back
    "pulse": 13,       # is the rhythm clearly defined
    "spectral": 15,    # is the tone balance an outlier within the batch
    "dynamics": 11,    # over-compressed or excessively dynamic
    "stereo": 3,       # guard only: catches mono and out-of-phase width
    "loudness": 14,    # consistent with the batch, with peak headroom
}
assert sum(WEIGHTS.values()) == 100


# A percentile ramp stretches p10..p90 across the full score range whatever that
# interval actually is. When a batch is degenerate -- takes of one track, or a handful
# of near-identical files -- that interval is noise, and the ramp turns a 2% measurement
# difference into a full-marks difference. Measured: six encodings of ONE song, whose raw
# motif and pulse values agreed to within 5%, scored 78.6 to 94.1.
#
# Below this relative spread, a cohort metric carries no ranking information and is
# flattened to neutral instead of amplified.
MIN_COHORT_SPREAD = 0.20


def _ramp(x, good, bad):
    """Linear falloff: 1.0 at `good`, 0.0 at `bad`."""
    if good == bad:
        return 1.0
    v = (x - bad) / (good - bad)
    return float(np.clip(v, 0.0, 1.0))


def _cohort_spread(lo: float, hi: float) -> float:
    """Relative width of a percentile interval, robust to values near zero."""
    denom = max(abs(hi), abs(lo), 1e-9)
    return (hi - lo) / denom


def _band(x, lo_bad, lo_ok, hi_ok, hi_bad):
    """1.0 inside [lo_ok, hi_ok], falling to 0.0 outside."""
    if x is None:
        return 0.5
    if lo_ok <= x <= hi_ok:
        return 1.0
    if x < lo_ok:
        return _ramp(x, lo_ok, lo_bad)
    return _ramp(x, hi_ok, hi_bad)


def score_cohort(results: list[dict]) -> list[dict]:
    """Add a 0-100 score and its breakdown to every track in the batch."""
    ok = [r for r in results if "metrics" in r]
    if not ok:
        return results

    profiles = np.array([r["metrics"]["spectral_profile"] for r in ok])
    median_profile = np.median(profiles, axis=0)

    lufs_vals = [r["loudness"]["lufs"] for r in ok if r["loudness"].get("lufs") is not None]
    median_lufs = float(np.median(lufs_vals)) if lufs_vals else -14.0

    motifs = np.array([r["metrics"]["motif_repetition"] for r in ok])
    motif_lo, motif_hi = float(np.percentile(motifs, 10)), float(np.percentile(motifs, 90))
    motif_usable = _cohort_spread(motif_lo, motif_hi) >= MIN_COHORT_SPREAD

    pulses = np.array([r["metrics"].get("pulse_clarity", 0.0) for r in ok])
    pulse_lo, pulse_hi = float(np.percentile(pulses, 10)), float(np.percentile(pulses, 90))
    pulse_usable = _cohort_spread(pulse_lo, pulse_hi) >= MIN_COHORT_SPREAD

    flattened = [name for name, usable in
                 (("motif", motif_usable), ("pulse", pulse_usable)) if not usable]

    for r in ok:
        m, sub = r["metrics"], {}

        # Hook: time to full energy, plus onset density in the first 5 seconds.
        speed = _ramp(m["time_to_full_s"], good=0.5, bad=8.0)
        density = _ramp(m["onset_density_5s"], good=3.0, bad=0.3)
        sub["hook"] = WEIGHTS["hook"] * (0.6 * speed + 0.4 * density)

        # Motif repetition and pulse clarity, scored by position within the batch.
        # Floored at 0.2: mapping percentile straight to 0-1 makes the lowest track in a
        # small batch score zero, which exaggerates real differences.
        # A flattened metric scores everyone the same rather than ranking on noise.
        sub["motif"] = WEIGHTS["motif"] * (
            0.6 if not motif_usable
            else 0.2 + 0.8 * _ramp(m["motif_repetition"], good=motif_hi, bad=motif_lo))
        sub["pulse"] = WEIGHTS["pulse"] * (
            0.6 if not pulse_usable
            else 0.2 + 0.8 * _ramp(m.get("pulse_clarity", 0.0),
                                   good=pulse_hi, bad=pulse_lo))

        # Spectral balance: distance from the batch median (smaller is better).
        dist = float(np.sum(np.abs(np.array(m["spectral_profile"]) - median_profile)))
        sub["spectral"] = WEIGHTS["spectral"] * _ramp(dist, good=0.05, bad=0.45)

        # Dynamics: crest 8-16 dB and LRA 3-9 LU are healthy for background listening.
        crest = _band(m["crest_db"], 5, 8, 16, 22)
        lra = _band(r["loudness"].get("lra"), 0.5, 3.0, 9.0, 16.0)
        sub["dynamics"] = WEIGHTS["dynamics"] * (0.5 * crest + 0.5 * lra)

        # Stereo width: 0.15-0.7 is a natural range (0 = fully mono).
        sub["stereo"] = WEIGHTS["stereo"] * _band(m["stereo_width"], 0.0, 0.15, 0.70, 1.2)

        # Loudness consistency with the batch, plus true-peak headroom.
        lufs = r["loudness"].get("lufs")
        cons = _ramp(abs(lufs - median_lufs), good=0.0, bad=4.0) if lufs is not None else 0.5
        tp = r["loudness"].get("true_peak")
        headroom = 1.0 if tp is None else _ramp(tp, good=-1.5, bad=0.5)
        sub["loudness"] = WEIGHTS["loudness"] * (0.7 * cons + 0.3 * headroom)

        r["subscores"] = {k: round(v, 1) for k, v in sub.items()}
        base = float(sum(sub.values()))

        # Defect penalty. The grade decides rejection; the score only decides ranking.
        penalty = 0.0
        for d in r["defects"]:
            if d["severity"] == "severe":
                penalty += 25.0
            elif d["severity"] == "warn":
                penalty += 6.0
            # "info" spot-check hints carry no penalty -- they may be intentional.
        r["score"] = round(max(0.0, base - penalty), 1)
        r["score_before_penalty"] = round(base, 1)
        if flattened:
            r["flattened_metrics"] = flattened

    return results


import re

# Generators label alternate takes in the title itself -- "Alleyway Weather (Take 2)",
# "... (Version 2)", "... - take 3". Without stripping these, both takes are treated as
# separate tracks and BOTH end up in the episode. Observed in real output.
_TAKE_SUFFIX = re.compile(
    r"\s*(?:[-–—]\s*)?[\(\[]?\s*(?:take|version|ver|v)\s*[.#]?\s*\d+\s*[\)\]]?\s*$",
    re.IGNORECASE,
)


def normalize_title(title: str) -> str:
    """Strip a trailing take/version marker so takes of one track group together.

    A digit is required, so a real title like "Take Five" survives untouched.
    """
    prev = None
    out = (title or "").strip()
    while out != prev:  # handles "Song (Take 2) v3"
        prev = out
        out = _TAKE_SUFFIX.sub("", out).strip()
    return out or (title or "").strip()


def discrimination(results: list[dict]) -> list[dict]:
    """How much each metric actually separated this batch.

    A metric whose scores are near-identical across every track contributes nothing to
    the ranking, however sensible it looks. Reporting this lets someone running different
    material see whether the weights still earn their place, instead of trusting numbers
    tuned on someone else's generator.
    """
    scored = [r for r in results if r.get("subscores")]
    if len(scored) < 2:
        return []

    # Subscore spread alone is misleading for the percentile-ramped metrics: the ramp
    # stretches p10..p90 to full range whatever that interval is, so their subscore
    # spread is large by construction. Report the RAW spread for those, which is what
    # actually says whether the ranking means anything.
    raw_key = {"motif": "motif_repetition", "pulse": "pulse_clarity"}
    flattened = set(scored[0].get("flattened_metrics") or [])

    out = []
    for name, weight in WEIGHTS.items():
        vals = [r["subscores"].get(name, 0.0) for r in scored]
        spread = (max(vals) - min(vals)) / weight if weight else 0.0
        entry = {
            "metric": name,
            "weight": weight,
            "mean": round(sum(vals) / len(vals), 1),
            "spread": round(spread, 3),
        }

        key = raw_key.get(name)
        if key:
            raw = [r["metrics"].get(key, 0.0) for r in scored]
            lo, hi = float(np.percentile(raw, 10)), float(np.percentile(raw, 90))
            entry["raw_spread"] = round(_cohort_spread(lo, hi), 3)
            if name in flattened:
                entry["verdict"] = "flattened (no usable spread)"
            else:
                entry["verdict"] = ("weak" if entry["raw_spread"] < 0.35 else "good")
        else:
            entry["verdict"] = ("near-constant" if spread < 0.25
                                else "weak" if spread < 0.50 else "good")
        out.append(entry)
    return sorted(out, key=lambda d: -d["spread"])


def pick_best_takes(results: list[dict]) -> tuple[list[dict], list[dict]]:
    """Of several takes sharing a title, keep only the highest scoring one.

    A caller can set `group_key` to say what "the same track" means. Filenames carry a
    leading index that identifies the track, so `01_Untitled` and `02_Untitled` are two
    tracks rather than two takes -- merging them silently discards one.
    """
    by_title: dict[str, list[dict]] = {}
    for r in results:
        key = r.get("group_key") or normalize_title(r.get("title") or r["file"])
        by_title.setdefault(key, []).append(r)

    kept, dropped = [], []
    for title, takes in by_title.items():
        takes.sort(key=lambda t: (t.get("tier") == "RED", -t.get("score", 0)))
        winner = takes[0]
        # Present the clean title. The winning take may be the one labelled
        # "... (Take 2)", and that suffix would otherwise reach the tracklist,
        # the exported filename, and the published chapter timestamps.
        winner["raw_title"] = winner.get("title")
        # Use the winner's own title, not `title` -- that is the grouping KEY, which is
        # deliberately lowercased and may carry an index prefix ("14|paper lantern").
        # Publishing the key put internal syntax into the report, the exported
        # filenames and the chapter timestamps.
        winner["title"] = normalize_title(winner.get("title") or winner["file"])
        kept.append(winner)
        for t in takes[1:]:
            t["dropped_reason"] = f"lower-scoring take of the same title (kept: {winner['file']})"
            dropped.append(t)
    return kept, dropped
