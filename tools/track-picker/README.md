# track-picker

Screens a batch of generated tracks for defects, scores them on objective properties,
picks the better of each pair of takes, sequences the episode, and level-matches the
result.

Background and rationale: [quality screening](../../docs/03-quality-screening.md) and
[playlist sequencing](../../docs/04-playlist-sequencing.md).

## Requirements

- Python 3.9+
- `numpy`
- `ffmpeg` on PATH (or set `FFMPEG_BIN=/path/to/ffmpeg`)

```bash
pip install numpy
```

## Use

Analyze a folder you already have:

```bash
python3 run.py --dir ./audio --out ./report --episode "Episode Name"
```

Full pipeline, including level-matched output:

```bash
python3 run.py --dir ./audio --out ./ep06 \
  --episode "Episode Name" \
  --narrative narrative.json \
  --export --require-instrumental
```

Downloading straight from a web generator: run [`collect.js`](collect.js) in the
generator's browser tab, save the JSON, then:

```bash
python3 run.py --urls tracks.json --out ./ep06 --episode "Episode Name" --export
```

## Options

| Flag | Meaning |
|---|---|
| `--dir` | Folder of existing audio files |
| `--urls` | JSON from `collect.js` — downloads first |
| `--out` | Output folder (required) |
| `--episode` | Title used in the report |
| `--limit N` | Cap the final playlist length |
| `--narrative` | `{"Track Title": 0.0-1.0}` — semantic order, 0 opens, 1 closes |
| `--export` | Also write numbered level-matched files, `.m3u`, and timestamps |
| `--export-format` | `m4a` (default), `wav`, or `flac` |
| `--require-instrumental` | Warn when a track's tags omit `instrumental` |

## Output

```
out/
  REPORT.md          grades, scores, spot-check points, playlist order, timestamps
  analysis.json      full per-track measurements
  playlist/          (with --export)
    01_Track_Name.m4a ...
    playlist.m3u
```

## Grades

| | Meaning |
|---|---|
| 🟢 GREEN | No defects |
| 🟡 YELLOW | Worth checking — hard cut, spectral seam, BPM far from target, possible vocals |
| 🔴 RED | A defect that cannot be intentional — regenerate |

RED is deliberately narrow: flattened-waveform clipping, contiguous mid-track silence,
and L/R phase inversion. Ambiguous findings — most importantly a beat that weakens, which
is indistinguishable from an intentional breakdown — are reported as spot-check
timestamps and do not affect the grade.

## Files

| File | Role |
|---|---|
| `analyze.py` | Per-track decoding, defect detection, feature extraction |
| `score.py` | Cohort-relative scoring, take selection |
| `sequence.py` | Playlist ordering |
| `export.py` | Loudness planning, encoding, M3U, timestamps |
| `run.py` | CLI and report generation |
| `collect.js` | Browser snippet for recovering audio URLs |

## Adapting to another generator

Only `collect.js` is service-specific. Adjust:

- `CLIP_RE` — the URL pattern of the audio files
- The `aria-label` matchers — how play buttons and the transport controls are labelled
- `bpmForTitle` / `tagsForTitle` — where BPM and tags appear in that page's text

Everything downstream operates on plain audio files.

## Limits

This does not judge whether a track is good. Scores rank candidates so you listen to five
tracks instead of thirty; they are not a verdict. Key estimation in particular is
unreliable on some material — the report marks low-confidence estimates with `?`, and the
sequencer down-weights them accordingly.
