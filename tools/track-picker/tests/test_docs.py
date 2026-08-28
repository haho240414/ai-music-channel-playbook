"""Cross-file consistency: docs against code, and the worked example against itself.

The main product of this repo is prose, and a reader who catches the docs contradicting
the code has no reason to trust the rest of it. Every invariant here was being held by
hand until now — and hand-maintenance already failed once, leaving a hardcoded 22 in the
sequencer after the hook weight became 24.

No audio, no ffmpeg.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(TOOL))
sys.path.insert(0, TOOL)

import analyze  # noqa: E402
import export  # noqa: E402
import sequence  # noqa: E402
from score import WEIGHTS  # noqa: E402


def read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- docs vs code

DOC_LABEL_TO_KEY = {
    "Hook immediacy": "hook",
    "Motif repetition": "motif",
    "Spectral balance": "spectral",
    "Loudness consistency": "loudness",
    "Pulse clarity": "pulse",
    "Dynamics": "dynamics",
    "Stereo width": "stereo",
}


def _documented_weights() -> dict[str, int]:
    doc = read("docs", "03-quality-screening.md")
    found = {}
    for label, key in DOC_LABEL_TO_KEY.items():
        m = re.search(r"^\|\s*" + re.escape(label) + r"\s*\|\s*(\d+)\s*\|", doc, re.M)
        if m:
            found[key] = int(m.group(1))
    return found


def test_every_weight_is_documented():
    assert set(_documented_weights()) == set(WEIGHTS), \
        "the scoring table in docs/03 must list every metric in WEIGHTS"


@pytest.mark.parametrize("key", sorted(WEIGHTS))
def test_documented_weight_matches_code(key):
    documented = _documented_weights()
    assert documented.get(key) == WEIGHTS[key], \
        f"docs/03 says {key} is {documented.get(key)}, code says {WEIGHTS[key]}"


def test_weights_still_total_one_hundred_in_docs():
    assert sum(_documented_weights().values()) == 100


@pytest.mark.parametrize("const, value", [
    ("BPM_EXP", sequence.BPM_EXP),
    ("KEY_EXP", sequence.KEY_EXP),
])
def test_sequencing_exponents_appear_in_docs(const, value):
    """The superlinear exponents are quoted in prose; a change must reach the doc."""
    doc = read("docs", "04-playlist-sequencing.md")
    assert f"** {value}" in doc or f"**{value}" in doc or f" {value}" in doc, \
        f"docs/04 does not mention {const}={value}"


def test_true_peak_ceiling_matches_docs():
    doc = read("docs", "04-playlist-sequencing.md")
    assert f"{export.TP_CEILING:.0f} dBTP" in doc or "−1 dBTP" in doc or "-1 dBTP" in doc


def test_analysis_thresholds_are_sane():
    """Guards against a typo silently disabling a check."""
    assert 0.0 < analyze.UNRELIABLE_PULSE < analyze.WEAK_PULSE_CEILING < 1.0
    assert analyze.MIN_WEAK_WINDOWS >= 2
    assert export.TARGET_LUFS < 0 and export.TP_CEILING < 0


# ---------------------------------------------------------------- worked example

TRACK_ROW = re.compile(r"^\|\s*(\d{2})\s*\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|",
                       re.M)


def _example_tracks():
    return TRACK_ROW.findall(read("examples", "01-episode-brief.md"))


def test_example_brief_has_a_full_tracklist():
    rows = _example_tracks()
    assert len(rows) >= 12, f"only {len(rows)} tracks parsed from the example brief"


def test_example_narrative_covers_exactly_the_tracklist():
    rows = _example_tracks()
    narrative = json.loads(read("examples", "05-narrative.json"))
    assert {t for _, t, _, _ in rows} == set(narrative)


def test_example_narrative_runs_start_to_finish_in_order():
    rows = _example_tracks()
    narrative = json.loads(read("examples", "05-narrative.json"))
    values = [narrative[t] for _, t, _, _ in rows]
    assert values == sorted(values), "narrative positions must not go backwards"
    assert min(values) == 0.0 and max(values) == 1.0


@pytest.mark.parametrize("idx", range(12))
def test_example_prompt_matches_the_brief(idx):
    """Each per-track prompt must state the same BPM and key as the brief."""
    rows = _example_tracks()
    if idx >= len(rows):
        pytest.skip("fewer tracks than expected")
    num, title, bpm, key = rows[idx]
    prompts = read("examples", "02-song-prompts.md")

    m = re.search(re.escape(f"**{num}. {title}**") + r"(.{0,200})", prompts, re.S)
    assert m, f"no prompt found for {num}. {title}"
    body = m.group(1)

    got_bpm = re.search(r"(\d{2,3})\s*BPM", body)
    assert got_bpm and int(got_bpm.group(1)) == int(bpm), \
        f"{title}: brief says {bpm} BPM, prompt says {got_bpm and got_bpm.group(1)}"

    root = key.replace("♭", " flat").replace("♯", " sharp").split()[0].lower()
    assert root in body.lower(), f"{title}: prompt does not mention key {key}"


def test_example_readme_track_count_is_right():
    readme = read("examples", "README.md")
    n = len(_example_tracks())
    assert f"{n} tracks" in readme or f"{n}-track" in readme or f"**{n}" in readme, \
        f"examples/README does not state the actual track count ({n})"
