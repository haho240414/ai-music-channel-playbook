"""Cohort-relative scoring: every track is judged against its own batch.

There is no correct spectral balance or loudness for a genre, so rather than inventing
target numbers, spectral balance and loudness are scored by deviation from the batch
median. Only metrics with an unambiguous direction (hook immediacy, motif repetition)
use fixed thresholds.
"""
from __future__ import annotations

import numpy as np

WEIGHTS = {
    "hook": 22,        # does it grab within the first 3-5 seconds
    "motif": 18,       # does a memorable figure come back
    "pulse": 12,       # is the rhythm clearly defined
    "spectral": 13,    # is the tone balance an outlier within the batch
    "dynamics": 13,    # over-compressed or excessively dynamic
    "stereo": 8,       # is there any width
    "loudness": 14,    # consistent with the batch, with peak headroom
}


def _ramp(x, good, bad):
    """Linear falloff: 1.0 at `good`, 0.0 at `bad`."""
    if good == bad:
        return 1.0
    v = (x - bad) / (good - bad)
    return float(np.clip(v, 0.0, 1.0))


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

    pulses = np.array([r["metrics"].get("pulse_clarity", 0.0) for r in ok])
    pulse_lo, pulse_hi = float(np.percentile(pulses, 10)), float(np.percentile(pulses, 90))

    for r in ok:
        m, sub = r["metrics"], {}

        # Hook: time to full energy, plus onset density in the first 5 seconds.
        speed = _ramp(m["time_to_full_s"], good=0.5, bad=8.0)
        density = _ramp(m["onset_density_5s"], good=3.0, bad=0.3)
        sub["hook"] = WEIGHTS["hook"] * (0.6 * speed + 0.4 * density)

        # Motif repetition and pulse clarity, scored by position within the batch.
        # Floored at 0.2: mapping percentile straight to 0-1 makes the lowest track in a
        # small batch score zero, which exaggerates real differences.
        sub["motif"] = WEIGHTS["motif"] * (0.2 + 0.8 * _ramp(
            m["motif_repetition"], good=motif_hi, bad=motif_lo))
        sub["pulse"] = WEIGHTS["pulse"] * (0.2 + 0.8 * _ramp(
            m.get("pulse_clarity", 0.0), good=pulse_hi, bad=pulse_lo))

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

    return results


def pick_best_takes(results: list[dict]) -> tuple[list[dict], list[dict]]:
    """Of several takes sharing a title, keep only the highest scoring one."""
    by_title: dict[str, list[dict]] = {}
    for r in results:
        by_title.setdefault(r.get("title") or r["file"], []).append(r)

    kept, dropped = [], []
    for title, takes in by_title.items():
        takes.sort(key=lambda t: (t.get("tier") == "RED", -t.get("score", 0)))
        kept.append(takes[0])
        for t in takes[1:]:
            t["dropped_reason"] = f"lower-scoring take of the same title (kept: {takes[0]['file']})"
            dropped.append(t)
    return kept, dropped
