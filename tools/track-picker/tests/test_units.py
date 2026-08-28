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
from run import _leading_index, filename_to_title  # noqa: E402
import render  # noqa: E402

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


# ---------------------------------------------------------------- filename titles


@pytest.mark.parametrize("filename, expected", [
    # Explicit take markers -- strip these.
    ("01_Kettle_On_take1", "Kettle On"),
    ("01_Kettle_On_take2", "Kettle On"),
    ("03_Song_v2", "Song"),
    ("04_Song_Version_2", "Song"),
    # Ambiguous trailing letters and digits -- these are part of the title.
    # Stripping them collapsed "Movement 1/2/3" into one track and silently dropped
    # two of them from the episode.
    ("01_Movement_1", "Movement 1"),
    ("02_Movement_2", "Movement 2"),
    ("03_Movement_3", "Movement 3"),
    ("06_Track_A", "Track A"),
    ("07_Part_C", "Part C"),
    ("04_Interlude_II", "Interlude II"),
    ("05_Studio_54", "Studio 54"),
    ("08_Route_66", "Route 66"),
])
def test_filename_to_title(filename, expected):
    import run
    assert filename_to_title(filename) == expected


@pytest.mark.parametrize("names, expected_groups", [
    # An explicit take marker outranks the index -- real output pairs
    # "06_Alleyway_Weather" with "07_Alleyway_Weather_Take_2".
    (["06_Alleyway_Weather.m4a", "07_Alleyway_Weather_Take_2.m4a"], 1),
    (["17_Ticket_take1.m4a", "17_Ticket_take2.m4a"], 1),
    # With no marker anywhere, the leading index identifies the track. Merging these
    # would drop two of the three as losing takes.
    (["01_Untitled.m4a", "02_Untitled.m4a", "03_Untitled.m4a"], 3),
    (["01_Movement_1.m4a", "02_Movement_2.m4a", "03_Movement_3.m4a"], 3),
])
def test_group_keys_balance_index_against_take_markers(names, expected_groups):
    import run
    assert len(set(run.group_keys_for(names).values())) == expected_groups


def test_same_name_different_index_survives_take_selection(tmp_path):
    """Six identically named files under different indices are six tracks, not one
    track with five discarded takes."""
    import run
    for i in range(1, 7):
        (tmp_path / f"0{i}_Untitled.wav").write_bytes(b"")
    jobs = run.collect_from_dir(str(tmp_path))
    tracks = []
    for j in jobs:
        t = make_track(j["title"])
        t["group_key"] = j["group_key"]
        tracks.append(t)
    kept, dropped = pick_best_takes(tracks)
    assert len(kept) == 6 and dropped == []


def test_numbered_movements_stay_separate_tracks(tmp_path):
    """End-to-end guard on the data-loss case: three movements must not become one
    track with two takes discarded."""
    import run
    for n in (1, 2, 3):
        (tmp_path / f"0{n}_Movement_{n}.wav").write_bytes(b"")
    titles = [j["title"] for j in run.collect_from_dir(str(tmp_path))]
    assert titles == ["Movement 1", "Movement 2", "Movement 3"]

    tracks = [make_track(t) for t in titles]
    kept, dropped = pick_best_takes(tracks)
    assert len(kept) == 3 and dropped == []


# ---------------------------------------------------------------- report rendering


def _table_rows_are_aligned(text):
    """Every row must have the same number of UNESCAPED pipes as its table's rule."""
    import re
    bad, expect = [], None
    for line in text.splitlines():
        if re.match(r"^\|[-\s|]+\|$", line):
            expect = len(re.split(r"(?<!\\)\|", line))
        elif line.startswith("|") and expect:
            if len(re.split(r"(?<!\\)\|", line)) != expect:
                bad.append(line)
        elif not line.startswith("|"):
            expect = None
    return bad


def _report_for(titles, tmp_path):
    import run as R
    tracks = [make_track(t) for t in titles]
    score_cohort(tracks)
    pl = build_playlist(tracks)
    return open(R.write_report(str(tmp_path), "ep", pl, tracks, [], tracks)).read()


def test_report_survives_hostile_titles(tmp_path):
    """Generators invent titles. A pipe or newline in one silently breaks the markdown
    table for every row after it."""
    text = _report_for(["Pipe | In Title", "Under_score *star*", "Back`tick`",
                        "Newline\nInside", "Plain One"], tmp_path)
    assert _table_rows_are_aligned(text) == []
    assert r"Pipe \| In Title" in text
    assert "Newline\nInside" not in text        # the newline must not escape the row


def test_report_renders_a_flattened_metric(tmp_path):
    """The flattening added for degenerate batches introduced a verdict string the
    report's icon lookup did not know, and KeyError'd on exactly those batches."""
    import run as R
    tracks = _clone_batch(6, motif=0.36, pulse=0.51)
    score_cohort(tracks)
    assert tracks[0].get("flattened_metrics"), "expected this batch to flatten"
    pl = build_playlist(tracks)
    text = open(R.write_report(str(tmp_path), "ep", pl, tracks, [], tracks)).read()
    assert "flattened" in text
    assert _table_rows_are_aligned(text) == []


def test_report_icon_lookup_is_total():
    """Any future verdict string must degrade, not crash."""
    import inspect

    import run as R
    src = inspect.getsource(R.write_report)
    assert '}.get(d["verdict"]' in src, "icon lookup must use .get with a default"


# ---------------------------------------------------------------- missing decoder


def test_missing_ffmpeg_is_a_distinct_exception(tmp_path, monkeypatch):
    """"This file is broken" and "I have no decoder" look identical at the call site.
    Conflating them made the corrupt-download self-heal delete every file in a batch."""
    import analyze

    f = tmp_path / "a.m4a"
    f.write_bytes(b"not audio")
    monkeypatch.setattr(analyze, "FFMPEG", "/nonexistent/ffmpeg")
    with pytest.raises(analyze.FFmpegMissing):
        analyze.decode(str(f))
    assert f.exists(), "a missing decoder must never be treated as a bad file"


def test_ffmpeg_available_reports_absence(monkeypatch):
    import analyze
    monkeypatch.setattr(analyze, "FFMPEG", "/nonexistent/ffmpeg")
    assert analyze.ffmpeg_available() is False


def test_decode_failure_is_not_ffmpeg_missing(tmp_path):
    """A genuinely unreadable file must still raise the ordinary error, so the
    self-heal keeps working for the case it was written for."""
    import analyze
    if not analyze.ffmpeg_available():
        pytest.skip("ffmpeg not available")
    f = tmp_path / "broken.m4a"
    f.write_bytes(b"\x00" * 50000)
    with pytest.raises(Exception) as excinfo:
        analyze.decode(str(f))
    assert not isinstance(excinfo.value, analyze.FFmpegMissing)


# ---------------------------------------------------------------- download safety


def test_download_is_atomic(tmp_path, monkeypatch):
    """A process killed mid-download must not leave a partial file that later counts as
    a cache hit. Measured: a 20%-truncated 3 MB track is 611 KB and sails past any size
    check, then fails to decode on every subsequent run."""
    import io
    import json as _json
    import run

    urls = tmp_path / "u.json"
    urls.write_text(_json.dumps([{"title": "T", "urls": ["http://x/a.m4a"]}]))
    audio = tmp_path / "audio"

    class Boom(io.BytesIO):
        def read(self, *a):
            raise IOError("connection dropped")

    def exploding_urlopen(*a, **k):
        class Ctx:
            def __enter__(self): return Boom(b"")
            def __exit__(self, *e): return False
        return Ctx()

    monkeypatch.setattr(run.urllib.request, "urlopen", exploding_urlopen)
    with pytest.raises(SystemExit):        # every download failed
        run.download(str(urls), str(audio))

    leftovers = list(audio.glob("*")) if audio.exists() else []
    assert not any(p.suffix == ".m4a" for p in leftovers), leftovers
    assert not any(p.name.endswith(".part") for p in leftovers), leftovers


def test_one_dead_url_does_not_abort_the_batch(tmp_path, monkeypatch):
    """A single expired link used to abort the whole run with a bare traceback --
    discarding the 6 of 7 files that had already downloaded, and producing no report."""
    import io
    import json as _json
    import run

    urls = tmp_path / "u.json"
    urls.write_text(_json.dumps([
        {"title": "Good One", "urls": ["http://x/good1.m4a"]},
        {"title": "Dead One", "urls": ["http://x/dead.m4a"]},
        {"title": "Good Two", "urls": ["http://x/good2.m4a"]},
    ]))

    def fake_urlopen(req, timeout=None):
        if "dead" in req.full_url:
            raise OSError("HTTP Error 404: Not Found")
        payload = b"x" * 20000

        class Ctx:
            def __enter__(self): return io.BytesIO(payload)
            def __exit__(self, *e): return False
        return Ctx()

    monkeypatch.setattr(run.urllib.request, "urlopen", fake_urlopen)
    ok, failed = run.download(str(urls), str(tmp_path / "audio"))

    assert len(ok) == 2, [os.path.basename(j["path"]) for j in ok]
    assert len(failed) == 1
    assert "404" in failed[0]["error"]
    assert all(j.get("ok") for j in ok)


def test_all_downloads_failing_is_a_clean_error(tmp_path, monkeypatch):
    import json as _json
    import run

    urls = tmp_path / "u.json"
    urls.write_text(_json.dumps([{"title": "T", "urls": ["http://x/a.m4a"]}]))

    def always_fail(req, timeout=None):
        raise OSError("HTTP Error 500")

    monkeypatch.setattr(run.urllib.request, "urlopen", always_fail)
    with pytest.raises(SystemExit):
        run.download(str(urls), str(tmp_path / "audio"))


def test_downloaded_jobs_are_marked(tmp_path, monkeypatch):
    """run.py only deletes files it fetched itself; a --dir file must never be removed."""
    import json as _json
    import run

    import io
    urls = tmp_path / "u.json"
    urls.write_text(_json.dumps([{"title": "T", "urls": ["http://x/a.m4a"]}]))

    def ok_urlopen(req, timeout=None):
        class Ctx:
            def __enter__(self): return io.BytesIO(b"x" * 20000)
            def __exit__(self, *e): return False
        return Ctx()

    monkeypatch.setattr(run.urllib.request, "urlopen", ok_urlopen)
    from_urls, _ = run.download(str(urls), str(tmp_path / "a"))
    assert from_urls and all(j.get("downloaded") for j in from_urls)

    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "01_Song.wav").write_bytes(b"")
    from_dir = run.collect_from_dir(str(tmp_path / "d"))
    assert from_dir and not any(j.get("downloaded") for j in from_dir)


# ---------------------------------------------------------------- weights


def test_weights_sum_to_one_hundred():
    from score import WEIGHTS
    assert sum(WEIGHTS.values()) == 100


def test_opener_hook_scale_tracks_the_weight():
    """build_playlist normalizes the hook subscore by its maximum. That maximum has
    already changed once; a stale constant silently rescales the opener decision."""
    import inspect
    import sequence
    from score import WEIGHTS

    src = inspect.getsource(sequence.build_playlist)
    assert "hook_max = float(WEIGHTS" in src, "hook_max must be derived, not hardcoded"

    # A full-marks hook must win the opener slot. Energies are spread so the closer is
    # chosen unambiguously and does not accidentally consume the candidate.
    t = make_track("perfect", hook=float(WEIGHTS["hook"]), ttf=1.0,
                   score=50.0, lufs=-13.0)
    others = [make_track(f"o{i}", hook=1.0, ttf=9.0, score=40.0, lufs=-15.0 - i)
              for i in range(3)]
    order = build_playlist([t] + others)
    assert order[0]["title"] == "perfect"


def _clone_batch(n, motif, pulse):
    """n tracks whose cohort metrics are all but identical."""
    out = []
    for i in range(n):
        t = make_track(f"clone {i}")
        t["metrics"]["motif_repetition"] = motif + i * 0.001
        t["metrics"]["pulse_clarity"] = pulse + i * 0.001
        out.append(t)
    return out


def test_degenerate_cohort_does_not_manufacture_score_differences():
    """Six encodings of ONE song agreed to within 5% on the raw metrics yet scored
    78.6 to 94.1, because the percentile ramp stretches whatever interval it is given."""
    tracks = _clone_batch(6, motif=0.36, pulse=0.51)
    score_cohort(tracks)
    scores = [t["score"] for t in tracks]
    assert max(scores) - min(scores) < 2.0, scores
    assert set(tracks[0]["flattened_metrics"]) == {"motif", "pulse"}


def test_real_spread_cohort_is_not_flattened():
    """The guard must not fire on a batch that genuinely differs, or it would throw
    away the ranking it exists to produce."""
    tracks = _clone_batch(10, motif=0.30, pulse=0.30)
    for i, t in enumerate(tracks):          # widen to a realistic spread
        t["metrics"]["motif_repetition"] = 0.25 + i * 0.03
        t["metrics"]["pulse_clarity"] = 0.30 + i * 0.04
    score_cohort(tracks)
    assert not tracks[0].get("flattened_metrics")
    motifs = [t["subscores"]["motif"] for t in tracks]
    assert max(motifs) - min(motifs) > 5.0, motifs


def test_discrimination_reports_raw_spread_for_cohort_metrics():
    """Subscore spread is large by construction for a percentile ramp, so it cannot
    reveal a degenerate batch. Raw spread can."""
    from score import discrimination
    tracks = _clone_batch(6, motif=0.36, pulse=0.51)
    score_cohort(tracks)
    d = {x["metric"]: x for x in discrimination(tracks)}
    assert d["motif"]["raw_spread"] < 0.10
    assert "flattened" in d["motif"]["verdict"]
    assert "raw_spread" not in d["hook"]      # absolute metric, no raw column


def test_discrimination_flags_a_constant_metric():
    """A metric that scores every track identically contributes nothing to ranking."""
    from score import discrimination
    tracks = _episode(12)
    score_cohort(tracks)
    for t in tracks:                       # force one metric flat
        t["subscores"]["stereo"] = 3.0
    d = {x["metric"]: x for x in discrimination(tracks)}
    assert d["stereo"]["verdict"] == "near-constant"
    assert d["stereo"]["spread"] == 0.0
    assert any(x["verdict"] == "good" for x in d.values())


def test_discrimination_needs_two_tracks():
    from score import discrimination
    assert discrimination([]) == []
    one = _episode(1)
    score_cohort(one)
    assert discrimination(one) == []


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


@pytest.mark.parametrize("limit", [12, 10, 8, 6, 4, 3, 2, 1])
def test_limit_keeps_both_endpoints(limit):
    """Trimming by score alone discards whichever endpoint scores low. Measured on a
    real episode: --limit 8 dropped the track marked as the finale (narrative 1.0)."""
    from sequence import limit_playlist
    tracks = _episode(15)
    score_cohort(tracks)
    narrative = {t["title"]: i / 14 for i, t in enumerate(tracks)}
    # Make the intended finale the WORST scoring track, so score-only trimming would
    # certainly drop it.
    finale = next(t for t in tracks if narrative[t["title"]] == 1.0)
    finale["score"] = 1.0
    order = build_playlist(tracks, narrative=narrative)
    assert order[-1] is finale

    trimmed = limit_playlist(order, limit, narrative=narrative)
    assert len(trimmed) == limit
    assert [t["position"] for t in trimmed] == list(range(1, limit + 1))
    assert trimmed[0] is order[0]
    if limit >= 2:
        assert trimmed[-1] is finale, "the deliberate closer must survive trimming"


def test_limit_is_a_noop_when_already_short_enough():
    from sequence import limit_playlist
    tracks = _episode(6)
    score_cohort(tracks)
    order = build_playlist(tracks)
    assert limit_playlist(order, 10, narrative=None) is order
    assert limit_playlist(order, 0, narrative=None) is order


def test_limit_keeps_the_highest_scoring_middle():
    from sequence import limit_playlist
    tracks = _episode(12)
    score_cohort(tracks)
    order = build_playlist(tracks)
    trimmed = limit_playlist(order, 6)
    middle_kept = {t["title"] for t in trimmed[1:-1]}
    middle_all = sorted(order[1:-1], key=lambda t: -t["score"])
    assert middle_kept == {t["title"] for t in middle_all[:4]}


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


def test_timestamps_do_not_accumulate_rounding_drift():
    """Chapter timestamps sum per-track durations, so any rounding compounds. Storing
    duration at 0.1 s resolution put a 30-track episode ~1.5 s out by the end — enough
    to misplace a chapter at the one-second granularity timestamps are displayed in."""
    exact = 174.0631972789116
    rows = [{"title": f"T{i}", "duration_s": exact} for i in range(30)]
    lines, total = timestamp_lines(rows)
    assert total == pytest.approx(exact * 30, abs=1e-6)

    # The same episode with durations rounded to 0.1 s drifts measurably.
    rounded = [{"title": f"T{i}", "duration_s": round(exact, 1)} for i in range(30)]
    _, rough_total = timestamp_lines(rounded)
    assert abs(rough_total - total) > 0.5


def test_analysis_duration_is_not_rounded():
    """Guard the source of the precision: analyze_file must not pre-round."""
    import inspect

    import analyze
    src = inspect.getsource(analyze.analyze_file)
    assert '"duration_s": len(mono) / sr' in src, \
        "duration_s must keep full precision; timestamps accumulate it"


def test_timestamps_cross_the_hour():
    rows = [{"title": f"T{i}", "duration_s": 700.0} for i in range(7)]
    lines, _ = timestamp_lines(rows)
    assert lines[6].startswith("1:10:00 ")


# --- Titles published to the report, filenames and chapter timestamps -----------


def test_spaced_index_is_stripped_from_title():
    """Real folders name files "14 - Paper Lantern.wav". Requiring the separator to
    touch the digits left the index inside the title, so the on-screen track name
    said 14 while the track played at position 1."""
    assert filename_to_title("14 - Paper Lantern.wav") == "Paper Lantern"
    assert filename_to_title("01 - Harbour Kite II.wav") == "Harbour Kite II"
    assert _leading_index("14 - Paper Lantern.wav") == "14"


def test_numeric_title_without_separator_survives():
    """The separator is what makes a leading number an index. Without one it is part
    of the title and must not be eaten."""
    assert filename_to_title("1984 Nights.wav") == "1984 Nights"
    assert _leading_index("1984 Nights.wav") == ""


def test_published_title_is_not_the_grouping_key():
    """`group_key` is an internal identifier: lowercased, index-prefixed, pipe-joined.
    Publishing it put "|14 - paper lantern" into the report and the exported filenames."""
    results = [{"file": "a.wav", "title": "Paper Lantern",
                "group_key": "14|paper lantern", "score": 9.0, "tier": "GREEN"}]
    kept, _ = pick_best_takes(results)
    assert kept[0]["title"] == "Paper Lantern"
    assert "|" not in kept[0]["title"]


def test_take_suffix_still_stripped_from_published_title():
    """The reason the key was published in the first place: the winning take may be
    the one labelled "(Take 2)", and that must not reach the tracklist."""
    results = [
        {"file": "a.wav", "title": "Salt Air", "group_key": "salt air",
         "score": 5.0, "tier": "GREEN"},
        {"file": "b.wav", "title": "Salt Air (Take 2)", "group_key": "salt air",
         "score": 9.0, "tier": "GREEN"},
    ]
    kept, dropped = pick_best_takes(results)
    assert len(kept) == 1 and len(dropped) == 1
    assert kept[0]["file"] == "b.wav"        # the higher-scoring take won
    assert kept[0]["title"] == "Salt Air"    # but published without the marker


def test_concat_container_follows_the_source_format():
    """PCM has no tag in an MP4 container: concatenating a wav export into .m4a fails
    with "Could not find tag for codec pcm_s16le" and no video is produced."""
    assert render.concat_container(["a/01.wav", "a/02.wav"], "/o/ep") == "/o/ep.wav"
    assert render.concat_container(["a/01.m4a", "a/02.m4a"], "/o/ep") == "/o/ep.m4a"
    assert render.concat_container(["a/01.flac"], "/o/ep") == "/o/ep.flac"
    # Mixed inputs cannot all be copied into either one, so use a permissive container.
    assert render.concat_container(["a/01.wav", "a/02.m4a"], "/o/ep") == "/o/ep.mkv"


@pytest.mark.parametrize("h", [720, 1080, 1440, 2160])
def test_title_never_collides_with_the_wave_band(h):
    """Measured on a rendered frame the title occupied rows 780-862 and the wave box
    began at 931. Both are derived from the height, so a resolution or font-size change
    can silently close that gap and strike the title through at loud moments."""
    w, title_size, wave_h = int(h * 16 / 9), max(int(h * 0.050), 12), int(h * 0.120)
    geo = render.layout(w, h, title_size, wave_h)
    assert geo["title_bottom"] < geo["wave_top"], (
        f"title reaches {geo['title_bottom']}, wave box starts {geo['wave_top']}")
    assert geo["wave_bottom"] <= h


# --- Overlay colours have to survive the cover they sit on ----------------------


def test_contrast_is_symmetric_and_bounded():
    assert render.contrast((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0, abs=0.01)
    assert render.contrast((255, 255, 255), (0, 0, 0)) == pytest.approx(21.0, abs=0.01)
    assert render.contrast((128, 128, 128), (128, 128, 128)) == pytest.approx(1.0)


@pytest.mark.parametrize("bg", [(10, 10, 12), (250, 247, 240), (58, 46, 40)])
def test_force_contrast_reaches_the_target(bg):
    """Sampling a colour out of the artwork guarantees nothing. On a night photograph
    the darkest cluster measured 1.1:1 against a near-black background -- text that is
    simply not there."""
    for fg in [(9, 29, 29), (112, 80, 72), (240, 176, 48)]:
        out = render.force_contrast(fg, bg, 4.5)
        assert render.contrast(out, bg) >= 4.5 - 1e-9


def test_force_contrast_moves_toward_white_on_dark_backgrounds():
    dark = (12, 12, 14)
    out = render.force_contrast((40, 60, 60), dark, 7.0)
    assert render._srgb_lum(out) > render._srgb_lum((40, 60, 60))
    light = (250, 248, 242)
    out = render.force_contrast((160, 140, 130), light, 7.0)
    assert render._srgb_lum(out) < render._srgb_lum((160, 140, 130))


def test_shadow_polarity_opposes_the_text():
    assert render.shadow_for("0xF6F6F6").startswith("black")
    assert render.shadow_for("0x59321E").startswith("white")


@pytest.mark.parametrize("side", ["left", "right"])
def test_layout_x_is_an_expression_for_the_right_side(side):
    geo = render.layout(1920, 1080, 54, 129, side)
    if side == "left":
        assert geo["x"] == str(int(1920 * 0.068))
    else:
        assert geo["x"].startswith("w-tw-")
