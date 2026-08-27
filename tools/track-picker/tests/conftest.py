"""Shared fixtures.

Audio fixtures are synthesized with ffmpeg at test time rather than committed, so the
repo stays text-only and the tests run anywhere ffmpeg is installed.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyze import FFMPEG  # noqa: E402


def _have_ffmpeg() -> bool:
    try:
        subprocess.run([FFMPEG, "-version"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


needs_ffmpeg = pytest.mark.skipif(not _have_ffmpeg(),
                                  reason="ffmpeg not available (set FFMPEG_BIN)")


def _render(path: str, *args: str) -> str:
    cmd = [FFMPEG, "-y", "-v", "error", *args, path]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return path


@pytest.fixture(scope="session")
def audio_dir(tmp_path_factory):
    """A directory of synthetic WAVs, each engineered to trigger one condition."""
    d = tmp_path_factory.mktemp("fixtures")
    p = lambda name: str(d / name)  # noqa: E731

    # Clean: a tremolo'd tone has periodic onsets (so tempo/rhythm analysis has
    # something to find) and fades, so it should raise no defects at all.
    _render(p("clean.wav"),
            "-f", "lavfi", "-i", "sine=frequency=220:duration=20:sample_rate=44100",
            "-af", "tremolo=f=5:d=0.8,afade=in:st=0:d=0.5,afade=out:st=19:d=1,volume=0.5",
            "-ac", "2", "-c:a", "pcm_s16le")

    # Clipping: driven far past full scale so the waveform flattens.
    _render(p("clipped.wav"),
            "-f", "lavfi", "-i", "sine=frequency=220:duration=20:sample_rate=44100",
            "-af", "tremolo=f=5:d=0.8,volume=14",
            "-ac", "2", "-c:a", "pcm_s16le")

    # Dropout: a full second of silence in the middle of the track.
    _render(p("dropout.wav"),
            "-f", "lavfi", "-i", "sine=frequency=220:duration=20:sample_rate=44100",
            "-af", ("tremolo=f=5:d=0.8,volume=enable='between(t,9,10.5)':volume=0,"
                    "afade=in:st=0:d=0.5,afade=out:st=19:d=1,volume=0.5"),
            "-ac", "2", "-c:a", "pcm_s16le")

    # Phase inversion: right channel is the negated left.
    _render(p("phase.wav"),
            "-f", "lavfi", "-i", "sine=frequency=220:duration=20:sample_rate=44100",
            "-af", "tremolo=f=5:d=0.8,volume=0.5,pan=stereo|c0=c0|c1=-1*c0",
            "-c:a", "pcm_s16le")

    # Hard cut: full energy right up to the final sample, no fade.
    _render(p("hardcut.wav"),
            "-f", "lavfi", "-i", "sine=frequency=220:duration=20:sample_rate=44100",
            "-af", "tremolo=f=5:d=0.8,volume=0.5",
            "-ac", "2", "-c:a", "pcm_s16le")

    # --- edge cases ---

    _render(p("silent.wav"),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=10",
            "-c:a", "pcm_s16le")

    _render(p("mono.wav"),
            "-f", "lavfi", "-i", "sine=frequency=220:duration=20:sample_rate=44100",
            "-af", "tremolo=f=5:d=0.8,afade=in:st=0:d=0.5,afade=out:st=19:d=1,volume=0.5",
            "-ac", "1", "-c:a", "pcm_s16le")

    _render(p("tiny.wav"),
            "-f", "lavfi", "-i", "sine=frequency=220:duration=0.4:sample_rate=44100",
            "-ac", "2", "-c:a", "pcm_s16le")

    return d


def make_track(title="Track", bpm=100.0, camelot="8B", lufs=-15.0, true_peak=-1.0,
               score=60.0, hook=15.0, ttf=3.0, tier="GREEN", confidence=1.0,
               duration=180.0, path="/tmp/x.m4a", profile=None):
    """A minimal track dict shaped like analyze_file + score_cohort output."""
    return {
        "file": f"{title}.m4a",
        "path": path,
        "title": title,
        "duration_s": duration,
        "tier": tier,
        "score": score,
        "tempo": {"bpm": bpm, "period_frames": 50.0},
        "key": {"key": "C", "camelot": camelot, "confidence": confidence},
        "loudness": {"lufs": lufs, "lra": 6.0, "true_peak": true_peak},
        "metrics": {
            "time_to_full_s": ttf,
            "onset_density_5s": 2.0,
            "motif_repetition": 0.4,
            "pulse_clarity": 0.5,
            "stereo_width": 0.3,
            "crest_db": 12.0,
            "spectral_profile": profile or [0.10, 0.22, 0.27, 0.19, 0.13, 0.09],
        },
        "subscores": {"hook": hook, "motif": 10.0, "pulse": 8.0, "spectral": 10.0,
                      "dynamics": 10.0, "stereo": 6.0, "loudness": 10.0},
        "defects": [],
    }
