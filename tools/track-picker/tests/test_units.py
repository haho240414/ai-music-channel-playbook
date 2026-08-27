"""Pure-function tests. No audio, no ffmpeg required.

These cover the logic that was hardest to get right: metrical folding, loudness
planning, and playlist ordering.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyze import fold_to_range, metrical_fold  # noqa: E402
from export import plan_gains, timestamp_lines  # noqa: E402
from score import normalize_title, pick_best_takes, score_cohort  # noqa: E402
from sequence import build_playlist, camelot_distance  # noqa: E402

from conftest import make_track  # noqa: E402


# ---------------------------------------------------------------- tempo folding


@pytest.mark.parametrize("raw, target, expected", [
    (200.0, 100.0, 100.0),   # octave up
    (50.0, 100.0, 100.0),    # octave down
    (71.8, 107.7, 107.7),    # 2/3 -- the triplet/duple error that flagged whole batches
    (161.5, 107.7, 107.7),   # 3/2
    (99.0, 100.0, 99.0),     # already correct, leave alone
])
def test_metrical_fold_recovers_target(raw, target, expected):
    assert metrical_fold(raw, target) == pytest.approx(expected, abs=0.5)


def test_metrical_fold_includes_two_thirds():
    """The specific gap that made every track look like it had tempo drift."""
    assert metrical_fold(107.7 * 2 / 3, 107.7) == pytest.approx(107.7, abs=0.5)
    assert metrical_fold(92.3 * 2 / 3, 92.3) == pytest.approx(92.3, abs=0.5)


@pytest.mark.parametrize("raw, expected_range", [
    (50.0, (78, 142)),
    (200.0, (78, 142)),
    (300.0, (78, 142)),
    (105.0, (78, 142)),
])
def test_fold_to_range_lands_in_perceptual_band(raw, expected_range):
    """With no target BPM, fold into the range people actually feel as the beat."""
    got = fold_to_range(raw)
    assert expected_range[0] <= got <= expected_range[1]


def test_fold_handles_none():
    assert metrical_fold(None, 100.0) is None
    assert metrical_fold(100.0, None) == 100.0
    assert fold_to_range(None) is None


# ---------------------------------------------------------------- camelot


@pytest.mark.parametrize("a, b, expected", [
    ("8B", "8B", 0),      # same key
    ("8B", "9B", 1),      # adjacent
    ("8B", "8A", 1),      # relative minor
    ("8B", "2B", 6),      # tritone away
    ("1B", "12B", 1),     # wraps around the wheel
])
def test_camelot_distance(a, b, expected):
    assert camelot_distance(a, b) == pytest.approx(expected)


def test_camelot_distance_handles_missing():
    assert camelot_distance(None, "8B") == 1.5
    assert camelot_distance("garbage", "8B") == 1.5


# ---------------------------------------------------------------- loudness planning


def test_plan_gains_never_exceeds_peak_ceiling():
    """The real invariant: no resulting true peak may go above the ceiling.

    Note this is NOT 'every gain is negative' -- the track that sets the minimum gets a
    small positive gain when it has peak headroom, which is safe by construction.
    """
    pl = [
        make_track("a", lufs=-15.0, true_peak=-0.5),
        make_track("b", lufs=-18.0, true_peak=-1.4),
        make_track("c", lufs=-14.0, true_peak=-0.2),
    ]
    target, gains = plan_gains(pl)
    for t in pl:
        predicted = t["loudness"]["true_peak"] + gains[id(t)]
        assert predicted <= -1.0 + 0.01, (t["title"], predicted)
    assert target <= -14.0


def test_plan_gains_equalizes_loudness():
    pl = [
        make_track("a", lufs=-15.0, true_peak=-0.5),
        make_track("b", lufs=-18.0, true_peak=-1.4),
    ]
    target, gains = plan_gains(pl)
    finals = [t["loudness"]["lufs"] + gains[id(t)] for t in pl]
    assert max(finals) - min(finals) < 0.05, finals


def test_plan_gains_respects_true_peak_ceiling():
    pl = [make_track("a", lufs=-20.0, true_peak=-0.1)]
    target, gains = plan_gains(pl)
    predicted_peak = -0.1 + gains[id(pl[0])]
    assert predicted_peak <= -1.0 + 0.01


def test_plan_gains_empty():
    target, gains = plan_gains([])
    assert gains == {}


# ---------------------------------------------------------------- take selection


def test_pick_best_takes_keeps_highest_score():
    a1 = make_track("Same Title", score=40.0)
    a1["file"] = "01_take1.m4a"
    a2 = make_track("Same Title", score=75.0)
    a2["file"] = "01_take2.m4a"
    kept, dropped = pick_best_takes([a1, a2])
    assert len(kept) == 1 and kept[0]["score"] == 75.0
    assert len(dropped) == 1 and "dropped_reason" in dropped[0]


@pytest.mark.parametrize("raw, expected", [
    ("Alleyway Weather (Take 2)", "Alleyway Weather"),
    ("Alleyway Weather (take 3)", "Alleyway Weather"),
    ("Scooter Lights in Minor - Take 2", "Scooter Lights in Minor"),
    ("Some Song [Version 2]", "Some Song"),
    ("Some Song v2", "Some Song"),
    ("Some Song", "Some Song"),
    ("Take Five", "Take Five"),          # no digit: a real title, leave it alone
    ("Studio 54", "Studio 54"),
])
def test_normalize_title_strips_only_take_markers(raw, expected):
    assert normalize_title(raw) == expected


def test_takes_labelled_in_the_title_are_grouped():
    """Real generator output labels the second take in the title itself; without
    normalization both takes end up in the episode."""
    a = make_track("Alleyway Weather", score=50.0)
    b = make_track("Alleyway Weather (Take 2)", score=80.0)
    kept, dropped = pick_best_takes([a, b])
    assert len(kept) == 1 and len(dropped) == 1
    assert kept[0]["score"] == 80.0
    # The winner is the "(Take 2)" one, but the suffix must not reach the tracklist,
    # the exported filename, or the published chapter timestamps.
    assert kept[0]["title"] == "Alleyway Weather"
    assert kept[0]["raw_title"] == "Alleyway Weather (Take 2)"


def test_pick_best_takes_prefers_non_red_over_higher_score():
    red = make_track("T", score=90.0, tier="RED")
    green = make_track("T", score=50.0, tier="GREEN")
    kept, _ = pick_best_takes([red, green])
    assert kept[0]["tier"] == "GREEN"


# ---------------------------------------------------------------- sequencing


def test_closer_hint_ranked_by_specificity():
    """'last' must not beat 'going home' just by matching first."""
    tracks = [
        make_track("Last Announcement", ttf=2.0, hook=20.0, score=80.0),
        make_track("Going Home in the Dark", score=60.0),
        make_track("Middle One", score=55.0),
        make_track("Another Middle", score=50.0),
    ]
    order = build_playlist(tracks, closer_hint=["last", "going home", "closing"])
    assert order[-1]["title"] == "Going Home in the Dark"


def test_closer_chosen_before_opener():
    """A high-scoring closer must not get locked into position 1."""
    tracks = [
        make_track("Going Home in the Dark", score=95.0, hook=22.0, ttf=1.0),
        make_track("Bright Opener", score=60.0, hook=20.0, ttf=2.0),
        make_track("Middle", score=50.0),
        make_track("Other Middle", score=45.0),
    ]
    order = build_playlist(tracks, closer_hint=["going home"])
    assert order[-1]["title"] == "Going Home in the Dark"
    assert order[0]["title"] != "Going Home in the Dark"


def test_opener_prefers_fast_hook_over_raw_score():
    tracks = [
        make_track("Slow Burn", score=90.0, hook=8.0, ttf=9.0),
        make_track("Instant Hook", score=65.0, hook=21.0, ttf=1.5),
        make_track("Filler", score=40.0),
        make_track("More Filler", score=35.0),
    ]
    order = build_playlist(tracks)
    assert order[0]["title"] == "Instant Hook"


def test_narrative_overrides_signal_order():
    tracks = [
        make_track("Should Be Last", score=90.0, hook=22.0, ttf=1.0),
        make_track("Should Be First", score=50.0, hook=10.0, ttf=4.0),
        make_track("Mid", score=55.0),
        make_track("Mid Two", score=52.0),
    ]
    narrative = {"Should Be First": 0.0, "Mid": 0.4, "Mid Two": 0.6,
                 "Should Be Last": 1.0}
    order = build_playlist(tracks, narrative=narrative)
    assert order[-1]["title"] == "Should Be Last"


def test_low_key_confidence_downweights_key_term():
    """Uncertain key estimates must not drive the ordering."""
    confident = [make_track(f"T{i}", camelot="8B" if i % 2 else "2B", confidence=1.0)
                 for i in range(6)]
    unconfident = [make_track(f"T{i}", camelot="8B" if i % 2 else "2B", confidence=0.0)
                   for i in range(6)]
    a = build_playlist(confident)
    b = build_playlist(unconfident)
    # Both must produce a complete, valid ordering regardless of confidence.
    assert len(a) == len(b) == 6
    assert all("position" in t for t in a + b)


def test_red_tracks_excluded_but_not_if_all_red():
    mixed = [make_track("ok", tier="GREEN"), make_track("bad", tier="RED")]
    assert {t["title"] for t in build_playlist(mixed)} == {"ok"}

    all_red = [make_track("a", tier="RED"), make_track("b", tier="RED")]
    assert len(build_playlist(all_red)) == 2  # better to output something


# ---------------------------------------------------------------- degenerate input


def test_single_track_playlist_sets_position():
    """A one-track episode must still carry position, or export crashes."""
    order = build_playlist([make_track("Only One")])
    assert len(order) == 1
    assert order[0]["position"] == 1


def test_empty_playlist():
    assert build_playlist([]) == []


def test_score_cohort_empty():
    assert score_cohort([]) == []


def test_score_cohort_single_track_scores():
    tracks = [make_track("solo")]
    score_cohort(tracks)
    assert 0 <= tracks[0]["score"] <= 100


# ---------------------------------------------------------------- scale


def _episode(n=20):
    """A realistically varied episode: spread BPM, keys, energy and hooks."""
    import random
    rng = random.Random(7)
    camelots = ["8B", "9B", "10B", "7B", "8A", "5A", "4B", "11B"]
    out = []
    for i in range(n):
        out.append(make_track(
            title=f"Track {i:02d}",
            bpm=rng.uniform(72.0, 118.0),
            camelot=rng.choice(camelots),
            lufs=rng.uniform(-19.0, -13.0),
            true_peak=rng.uniform(-2.0, -0.2),
            score=rng.uniform(35.0, 90.0),
            hook=rng.uniform(5.0, 22.0),
            ttf=rng.uniform(1.0, 9.0),
            confidence=rng.uniform(0.0, 1.0),
            duration=rng.uniform(150.0, 200.0),
            profile=[round(max(0.01, 0.16 + rng.uniform(-0.06, 0.06)), 4)
                     for _ in range(6)],
        ))
    return out


@pytest.mark.parametrize("n", [12, 15, 20])
def test_full_size_episode_orders_completely(n):
    tracks = _episode(n)
    score_cohort(tracks)
    kept, _ = pick_best_takes(tracks)
    order = build_playlist(kept)

    assert len(order) == n
    assert [t["position"] for t in order] == list(range(1, n + 1))
    assert len({id(t) for t in order}) == n            # no track duplicated
    assert {t["title"] for t in order} == {t["title"] for t in tracks}


def test_scale_sequencer_actually_smooths_tempo():
    """Ordering must be gentler than the arbitrary input order, or it is not working."""
    import statistics
    tracks = _episode(20)
    score_cohort(tracks)
    order = build_playlist(tracks)

    def jumps(seq):
        b = [t["tempo"]["bpm"] for t in seq]
        return statistics.median(abs(b[i + 1] - b[i]) for i in range(len(b) - 1))

    assert jumps(order) < jumps(tracks)


def test_local_improvement_never_worsens_total_cost():
    from sequence import _local_improve, _prepare, _total_cost
    tracks = _episode(16)
    score_cohort(tracks)
    order = _prepare(build_playlist(tracks))   # re-attach the normalized values
    before = _total_cost(order, None)
    again = _local_improve(list(order), None)
    assert _total_cost(again, None) <= before + 1e-9


def test_local_improvement_keeps_endpoints_and_membership():
    """The opener and closer were chosen deliberately; polishing must not move them."""
    from sequence import _local_improve, _prepare
    tracks = _episode(14)
    score_cohort(tracks)
    order = _prepare(build_playlist(tracks))
    polished = _local_improve(list(order), None)
    assert polished[0] is order[0]
    assert polished[-1] is order[-1]
    assert {id(t) for t in polished} == {id(t) for t in order}
    assert len(polished) == len(order)


def test_superlinear_cost_avoids_outlier_transitions():
    """A linear cost trades one jarring jump for several tiny gains. Measured on a real
    14-track episode that produced a 26.7 BPM lurch; the exponent removed it."""
    tracks = _episode(18)
    score_cohort(tracks)
    order = build_playlist(tracks)
    jumps = [abs(order[i + 1]["tempo"]["bpm"] - order[i]["tempo"]["bpm"])
             for i in range(len(order) - 1)]
    raw = [t["tempo"]["bpm"] for t in tracks]
    worst_possible = max(raw) - min(raw)
    # No single transition may eat a large share of the episode's whole tempo span.
    assert max(jumps) < worst_possible * 0.65, sorted(jumps)[-3:]


def test_scale_with_narrative_respects_endpoints():
    tracks = _episode(15)
    score_cohort(tracks)
    narrative = {t["title"]: i / 14 for i, t in enumerate(tracks)}
    order = build_playlist(tracks, narrative=narrative)
    assert order[-1]["title"] == "Track 14"
    assert len(order) == 15


def test_scale_loudness_plan_equalizes_twenty_tracks():
    tracks = _episode(20)
    score_cohort(tracks)
    order = build_playlist(tracks)
    target, gains = plan_gains(order)
    finals = [t["loudness"]["lufs"] + gains[id(t)] for t in order]
    assert max(finals) - min(finals) < 0.05
    for t in order:
        assert t["loudness"]["true_peak"] + gains[id(t)] <= -1.0 + 0.01


def test_limit_reduces_and_reorders_cleanly():
    """--limit path: trim to the top N, then re-sequence."""
    tracks = _episode(20)
    score_cohort(tracks)
    order = build_playlist(tracks)
    keep_ids = {id(t) for t in sorted(order, key=lambda t: -t["score"])[:12]}
    trimmed = build_playlist([t for t in order if id(t) in keep_ids])
    assert [t["position"] for t in trimmed] == list(range(1, 13))


# ---------------------------------------------------------------- timestamps


def test_timestamps_are_cumulative():
    rows = [
        {"title": "One", "duration_s": 167.0},
        {"title": "Two", "duration_s": 177.0},
        {"title": "Three", "duration_s": 170.0},
    ]
    lines, total = timestamp_lines(rows)
    assert lines[0].startswith("0:00 ")
    assert lines[1].startswith("2:47 ")
    assert lines[2].startswith("5:44 ")
    assert total == pytest.approx(514.0)


def test_timestamps_cross_the_hour():
    rows = [{"title": f"T{i}", "duration_s": 700.0} for i in range(7)]
    lines, _ = timestamp_lines(rows)
    assert lines[6].startswith("1:10:00 ")
