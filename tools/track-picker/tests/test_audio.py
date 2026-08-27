"""Detector and pipeline tests against synthesized audio.

Each fixture is engineered to trigger exactly one condition, so a detector firing on the
wrong fixture is a false positive we want to catch.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyze import analyze_file, decode, loudness  # noqa: E402
from export import export_playlist  # noqa: E402
from score import pick_best_takes, score_cohort  # noqa: E402
from sequence import build_playlist  # noqa: E402

from conftest import needs_ffmpeg  # noqa: E402

pytestmark = needs_ffmpeg


def types_of(result):
    return {d["type"] for d in result["defects"]}


def severe_of(result):
    return {d["type"] for d in result["defects"] if d["severity"] == "severe"}


# ---------------------------------------------------------------- detectors fire


def test_clipping_detected(audio_dir):
    r = analyze_file(str(audio_dir / "clipped.wav"))
    assert "clipping" in types_of(r)
    assert r["tier"] == "RED"


def test_dropout_detected(audio_dir):
    r = analyze_file(str(audio_dir / "dropout.wav"))
    assert "dropout" in types_of(r)
    assert r["tier"] == "RED"


def test_phase_inversion_detected(audio_dir):
    r = analyze_file(str(audio_dir / "phase.wav"))
    assert "phase" in types_of(r)
    assert r["tier"] == "RED"


def test_hard_cut_detected(audio_dir):
    r = analyze_file(str(audio_dir / "hardcut.wav"))
    assert "hard_cut" in types_of(r)


# ---------------------------------------------------------------- no false positives


def test_clean_audio_has_no_severe_defects(audio_dir):
    """The most important test: a clean track must come back clean.

    Earlier versions flagged every track's own fade-out as a dropout and every track's
    triplet feel as tempo drift.
    """
    r = analyze_file(str(audio_dir / "clean.wav"))
    assert severe_of(r) == set(), r["defects"]
    assert r["tier"] in ("GREEN", "YELLOW")


def test_clean_audio_fade_out_not_called_a_dropout(audio_dir):
    r = analyze_file(str(audio_dir / "clean.wav"))
    assert "dropout" not in types_of(r)


def test_clean_audio_not_flagged_as_clipping(audio_dir):
    r = analyze_file(str(audio_dir / "clean.wav"))
    assert "clipping" not in types_of(r)


def test_clean_stereo_not_flagged_as_phase(audio_dir):
    r = analyze_file(str(audio_dir / "clean.wav"))
    assert "phase" not in types_of(r)


# ---------------------------------------------------------------- measurement sanity


def test_loudness_measured(audio_dir):
    m = loudness(str(audio_dir / "clean.wav"))
    assert m["lufs"] is not None and -70 < m["lufs"] < 0
    assert m["true_peak"] is not None


def test_tempo_matches_known_modulation_rate(audio_dir):
    """The fixture is amplitude-modulated at 5 Hz = 300 BPM, folded into the
    perceptual band as 150 -> 75 BPM. Accept any metrical relative of 300."""
    r = analyze_file(str(audio_dir / "clean.wav"))
    bpm = r["tempo"]["bpm"]
    assert bpm is not None
    ratios = [300.0 / bpm * f for f in (1,)]
    assert any(abs(300.0 / bpm - k) < 0.15 * k for k in (1, 2, 3, 4, 6, 8)), bpm


def test_blind_tempo_picks_a_grid_the_music_supports(audio_dir):
    """With no target BPM, the metrical level must be chosen by how well a beat grid
    explains the signal -- not by closeness to a preferred tempo.

    Picking by preference alone put 6 of 30 real tracks on a grid that ANTI-aligned with
    the music (negative pulse clarity), which made the whole rhythm analysis garbage.
    """
    from analyze import onset_envelope, pulse_strength
    r = analyze_file(str(audio_dir / "clean.wav"))
    _, _, mono = decode(str(audio_dir / "clean.wav"))
    onset, rate = onset_envelope(mono, 22050)
    strength = pulse_strength(onset, 60.0 * rate / r["tempo"]["bpm"])
    assert strength > 0.10, (r["tempo"]["bpm"], strength)


def test_unreliable_grid_emits_no_spot_checks(audio_dir):
    """When the grid does not explain the music, listing 33 'weak' windows out of 36 is
    noise. Report the low clarity instead and stay quiet."""
    from analyze import rhythm_stability, rms_envelope, onset_envelope
    _, _, mono = decode(str(audio_dir / "clean.wav"))
    env = rms_envelope(mono, 22050, 0.1)
    onset, rate = onset_envelope(mono, 22050)
    # Force a nonsense beat period so the grid cannot align.
    bogus = rhythm_stability(onset, rate, period=rate * 0.37, rms_env=env)
    if bogus.get("clarity_median") is not None and bogus["clarity_median"] < 0.10:
        assert bogus["weak_windows"] == []
        assert bogus.get("grid_unreliable") is True


def test_key_reports_confidence(audio_dir):
    r = analyze_file(str(audio_dir / "clean.wav"))
    assert 0.0 <= r["key"]["confidence"] <= 1.0


def test_analysis_shape(audio_dir):
    r = analyze_file(str(audio_dir / "clean.wav"))
    for field in ("file", "duration_s", "tempo", "rhythm", "key", "loudness",
                  "metrics", "defects", "tier", "spot_check"):
        assert field in r, field
    assert len(r["metrics"]["spectral_profile"]) == 6


# ---------------------------------------------------------------- edge cases


def test_mono_file_does_not_crash(audio_dir):
    r = analyze_file(str(audio_dir / "mono.wav"))
    assert r["tier"] in ("GREEN", "YELLOW", "RED")
    # A mono source is dual-mono after decode: zero width, and definitely not
    # out of phase with itself.
    assert r["metrics"]["stereo_width"] == pytest.approx(0.0, abs=1e-6)
    assert "phase" not in types_of(r)


def test_silent_file_does_not_crash(audio_dir):
    r = analyze_file(str(audio_dir / "silent.wav"))
    assert r["tier"] in ("GREEN", "YELLOW", "RED")


def test_silent_file_is_not_scored_as_an_instant_hook(audio_dir):
    """Silence trivially 'reaches full energy' at t=0; that must not read as a hook."""
    r = analyze_file(str(audio_dir / "silent.wav"))
    score_cohort([r])
    assert r["subscores"]["hook"] < 12.0, r["metrics"]


def test_very_short_file_does_not_crash(audio_dir):
    r = analyze_file(str(audio_dir / "tiny.wav"))
    assert r["duration_s"] < 1.0
    assert "metrics" in r


# ---------------------------------------------------------------- pipeline


def test_full_pipeline_end_to_end(audio_dir, tmp_path):
    names = ["clean.wav", "hardcut.wav", "dropout.wav", "mono.wav"]
    results = []
    for n in names:
        r = analyze_file(str(audio_dir / n))
        r["title"] = n.replace(".wav", "")
        results.append(r)

    score_cohort(results)
    kept, dropped = pick_best_takes(results)
    playlist = build_playlist(kept)

    assert len(playlist) >= 1
    assert all("position" in t for t in playlist)
    assert [t["position"] for t in playlist] == list(range(1, len(playlist) + 1))

    rows, pl_dir, common = export_playlist(playlist, str(tmp_path), fmt="wav")
    assert all(r["ok"] for r in rows), rows
    assert os.path.exists(os.path.join(pl_dir, "playlist.m3u"))
    for r in rows:
        assert os.path.exists(os.path.join(pl_dir, r["file"]))


def test_export_equalizes_loudness_in_practice(audio_dir, tmp_path):
    """Not just the plan -- re-measure the rendered files."""
    results = []
    for n, gain in (("clean.wav", None), ("hardcut.wav", None)):
        r = analyze_file(str(audio_dir / n))
        r["title"] = n.replace(".wav", "")
        results.append(r)
    score_cohort(results)
    playlist = build_playlist(results)
    rows, pl_dir, common = export_playlist(playlist, str(tmp_path), fmt="wav")

    measured = [loudness(os.path.join(pl_dir, r["file"]))["lufs"] for r in rows]
    measured = [m for m in measured if m is not None]
    assert max(measured) - min(measured) < 0.6, measured


def test_single_track_export_does_not_crash(audio_dir, tmp_path):
    """Regression: build_playlist used to return a one-track episode without a
    position, which crashed export."""
    r = analyze_file(str(audio_dir / "clean.wav"))
    r["title"] = "solo"
    score_cohort([r])
    playlist = build_playlist([r])
    rows, pl_dir, _ = export_playlist(playlist, str(tmp_path), fmt="wav")
    assert len(rows) == 1 and rows[0]["ok"]


def test_all_red_batch_still_produces_a_playlist(audio_dir, tmp_path):
    results = []
    for n in ("clipped.wav", "dropout.wav"):
        r = analyze_file(str(audio_dir / n))
        r["title"] = n.replace(".wav", "")
        results.append(r)
    score_cohort(results)
    playlist = build_playlist(results)
    assert len(playlist) == 2
    assert all("position" in t for t in playlist)
