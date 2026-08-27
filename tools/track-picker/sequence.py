"""Playlist ordering: choose track 1, then sequence by key, tempo, and energy flow.

Principles
 1) Track 1 is not simply the best track -- it is the one that grabs fastest, because
    that is what defends against leaving in the first 30 seconds.
 2) The closing track is chosen FIRST, before the opener (see build_playlist).
 3) The middle minimizes transition cost between adjacent tracks (Camelot key distance,
    BPM, energy, brightness) while following a gentle overall energy arc.
"""
from __future__ import annotations

import numpy as np

# Transition cost weights
W_BPM = 0.35
W_KEY = 0.35
W_ENERGY = 0.20
W_BRIGHT = 0.10
W_ARC = 0.60   # deviation from the target energy arc
W_NARR = 1.40  # narrative position hint, when supplied

# Exponents >1 make a single jarring transition cost more than the sum of the small
# improvements it could buy elsewhere. See _pair_cost.
BPM_EXP = 1.7
KEY_EXP = 1.5


def camelot_distance(a: str | None, b: str | None) -> float:
    """Camelot wheel distance. 0 = same key, 1 = adjacent or relative major/minor."""
    if not a or not b:
        return 1.5
    try:
        na, la = int(a[:-1]), a[-1]
        nb, lb = int(b[:-1]), b[-1]
    except (ValueError, IndexError):
        return 1.5
    step = min((na - nb) % 12, (nb - na) % 12)
    return step if la == lb else step + 1.0


def _brightness(r: dict) -> float:
    """Stand-in for spectral centroid: share of energy in the upper bands."""
    p = r["metrics"]["spectral_profile"]
    return float(sum(p[3:]))


def _energy(r: dict) -> float:
    lufs = r["loudness"].get("lufs")
    return float(lufs) if lufs is not None else -14.0


def _norm(vals: list[float]) -> dict:
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    return {"lo": lo, "span": span}


def _target_arc(i: int, n: int) -> float:
    """Normalized 0-1 target energy curve.

    Opens strong (the hook holds the listener), peaks around 60% through, then descends
    to resolve -- the shape that suits a time-of-day progression.
    """
    if n <= 1:
        return 0.80
    x = i / (n - 1)
    if x < 0.6:
        return 0.75 + 0.15 * (x / 0.6)
    return 0.90 - 0.65 * ((x - 0.6) / 0.4) ** 1.3


def _narr(t: dict, narrative: dict | None):
    """Title -> narrative position (0.0 = opens the episode, 1.0 = closes it)."""
    if not narrative:
        return None
    title = (t.get("title") or "").strip().lower()
    for k, v in narrative.items():
        if k.strip().lower() == title:
            return float(v)
    return None


# ---------------------------------------------------------------- cost model

# The cost model works on normalized energy/brightness, which only mean anything
# relative to the rest of the batch. `_prepare` attaches them; `_cleanup` removes them
# so they never reach the exported JSON.
_TEMP_KEYS = ("_e", "_b", "_bpm")


def _prepare(pool: list[dict]) -> list[dict]:
    energies = [_energy(t) for t in pool]
    brights = [_brightness(t) for t in pool]
    en, bn = _norm(energies), _norm(brights)
    for t, e, b in zip(pool, energies, brights):
        t["_e"] = (e - en["lo"]) / en["span"]
        t["_b"] = (b - bn["lo"]) / bn["span"]
        t["_bpm"] = t["tempo"]["bpm"] or 96.0
    return pool


def _cleanup(pool: list[dict]) -> None:
    for t in pool:
        for k in _TEMP_KEYS:
            t.pop(k, None)


def _pair_cost(prev: dict, cand: dict) -> float:
    """Cost of playing `cand` directly after `prev`. Symmetric in its inputs.

    The tempo and key terms are deliberately **superlinear**. With a linear cost the
    optimizer trades one jarring transition for several tiny improvements elsewhere,
    which is a bad deal perceptually: a listener notices a 27 BPM lurch and does not
    notice five 5 BPM steps. Raising the exponent makes outlier transitions expensive
    enough that they get avoided rather than amortized.
    """
    d_bpm = abs(cand["_bpm"] - prev["_bpm"]) / 10.0
    # Do not trust the key term between tracks whose key estimate is uncertain.
    # Measured margins ranged from 0.29 down to 0.03.
    key_conf = min(prev["key"].get("confidence", 1.0), cand["key"].get("confidence", 1.0))
    d_key = camelot_distance(prev["key"]["camelot"], cand["key"]["camelot"])
    return (
        W_BPM * (d_bpm ** BPM_EXP)
        + W_KEY * (d_key ** KEY_EXP) * key_conf
        + W_ENERGY * abs(cand["_e"] - prev["_e"]) * 3.0
        + W_BRIGHT * abs(cand["_b"] - prev["_b"]) * 3.0
    )


def _slot_cost(cand: dict, pos: int, n_total: int, narrative: dict | None) -> float:
    """Cost of `cand` sitting at position `pos`, independent of its neighbours."""
    cost = (W_ARC * abs(cand["_e"] - _target_arc(pos, n_total)) * 3.0
            - cand["score"] / 100.0)  # weak pull bringing better tracks earlier
    nv = _narr(cand, narrative)
    if nv is not None:
        cost += W_NARR * abs(nv - pos / max(1, n_total - 1)) * 3.0
    return cost


def _total_cost(order: list[dict], narrative: dict | None) -> float:
    n = len(order)
    total = 0.0
    for i, t in enumerate(order):
        if i:
            total += _pair_cost(order[i - 1], t)
        total += _slot_cost(t, i, n, narrative)
    return total


def _local_improve(order: list[dict], narrative: dict | None,
                   max_rounds: int = 40) -> list[dict]:
    """Polish the greedy result with 2-opt and relocation moves.

    Greedy nearest-neighbour commits early and spends the good transitions at the front,
    so the tail of a real episode ends up with the jumps nobody wanted. Measured on a
    14-track episode, the greedy tail carried BPM jumps of 15, 15 and 16 and a key
    distance of 4 on the final transition.

    Position 1 and the last position stay fixed -- both were chosen deliberately and are
    not the sequencer's to overrule.
    """
    n = len(order)
    if n < 5:
        return order

    best_cost = _total_cost(order, narrative)
    for _ in range(max_rounds):
        improved = False

        # 2-opt: reverse an interior segment.
        for i in range(1, n - 2):
            for j in range(i + 1, n - 1):
                cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                c = _total_cost(cand, narrative)
                if c < best_cost - 1e-9:
                    order, best_cost, improved = cand, c, True

        # Relocation: lift one interior track and reinsert it elsewhere.
        for i in range(1, n - 1):
            rest = order[:i] + order[i + 1:]
            for j in range(1, n - 1):
                if j == i:
                    continue
                cand = rest[:j] + [order[i]] + rest[j:]
                c = _total_cost(cand, narrative)
                if c < best_cost - 1e-9:
                    order, best_cost, improved = cand, c, True
                    break
            if improved:
                break

        if not improved:
            break
    return order


def build_playlist(tracks: list[dict], closer_hint: list[str] | None = None,
                   hook_max: float = 22.0, narrative: dict | None = None) -> list[dict]:
    """Order the episode using score, key, tempo, and energy.

    Pass `narrative` (title -> 0.0-1.0) to supply semantic order. Signal analysis cannot
    know that a title like "Chairs Stacked, Lights Off" is an ending image.
    """
    pool = [t for t in tracks if t.get("tier") != "RED"] or list(tracks)
    if len(pool) <= 1:
        # Still assign position -- export and the report both index on it, so
        # returning a bare track here crashes a one-track episode.
        for i, t in enumerate(pool, 1):
            t["position"] = i
        return pool

    _prepare(pool)
    bpms = [(t["tempo"]["bpm"] or 96.0) for t in pool]

    # --- Choose the CLOSER first.
    #     Picking the opener first means a track that is obviously the episode's ending
    #     gets locked into position 1 just because its numbers are good, and is then no
    #     longer available to close.
    #
    #     Title hints are ranked by specificity: a short keyword like "last" otherwise
    #     matches "Chairs Stacked, Lights Off" before the intended "The Long Way
    #     Home" is ever compared.
    closer = None
    narr_vals = [(t, _narr(t, narrative)) for t in pool]
    scored_narr = [(t, v) for t, v in narr_vals if v is not None]
    if scored_narr:
        closer = max(scored_narr, key=lambda p: p[1])[0]
    elif closer_hint:
        best_len, best_t = 0, None
        for t in pool:
            title = (t.get("title") or "").lower()
            for h in closer_hint:
                h = h.lower()
                if h in title and len(h) > best_len:
                    best_len, best_t = len(h), t
        closer = best_t
    if closer is None and len(pool) > 3:
        closer = min(pool, key=lambda t: t["_e"] * 0.6 + (t["_bpm"] / max(bpms)) * 0.4)

    candidates = [t for t in pool if t is not closer]
    if not candidates:
        candidates, closer = pool, None

    # --- Track 1: hook dominates. A track that takes too long to arrive does not open.
    def opener_value(t):
        hook_ratio = t["subscores"].get("hook", 0) / hook_max
        ttf = t["metrics"].get("time_to_full_s", 99)
        immediacy = 1.0 if ttf <= 5.0 else (0.6 if ttf <= 8.0 else 0.3)
        base = 0.5 * t["score"] + 40.0 * hook_ratio
        val = base * immediacy - (10.0 if t["tier"] == "YELLOW" else 0.0)
        nv = _narr(t, narrative)
        if nv is not None:
            val -= 45.0 * nv  # push narratively-late tracks out of contention for #1
        return val

    opener = max(candidates, key=opener_value)
    rest = [t for t in candidates if t is not opener]

    # --- Middle: greedy nearest neighbour over transition cost plus arc fit.
    order = [opener]
    n_total = len(pool)
    while rest:
        prev = order[-1]
        pos = len(order)
        best, best_cost = None, float("inf")
        for cand in rest:
            cost = _pair_cost(prev, cand) + _slot_cost(cand, pos, n_total, narrative)
            if cost < best_cost:
                best, best_cost = cand, cost
        order.append(best)
        rest.remove(best)

    if closer is not None:
        order.append(closer)

    # Greedy spends its good transitions early; polish the interior.
    order = _local_improve(order, narrative)

    for i, t in enumerate(order, 1):
        t["position"] = i
        if i > 1:
            p = order[i - 2]
            t["transition"] = {
                "d_bpm": round(t["_bpm"] - p["_bpm"], 1),
                "key_dist": round(camelot_distance(p["key"]["camelot"], t["key"]["camelot"]), 1),
                "d_energy_lu": round(_energy(t) - _energy(p), 1),
            }
    _cleanup(order)
    return order
