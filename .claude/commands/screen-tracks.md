---
description: Screen generated tracks for defects, pick takes, sequence, and level-match
---

Read `docs/03-quality-screening.md` and `docs/04-playlist-sequencing.md`.

Run the tool on the user's audio folder:

```bash
python3 tools/track-picker/run.py --dir <AUDIO_DIR> --out <OUT_DIR> \
  --episode "<EPISODE>" --export --require-instrumental
```

Add `--narrative <file.json>` if the episode has a semantic order — signal analysis cannot
know which title is an ending image.

If ffmpeg is missing, tell the user to install it or set `FFMPEG_BIN`.

Then report:
- Any RED tracks and what defect was found, with timestamps — these need regenerating
- Which take was kept per title
- The proposed order and why track 1 opens
- The loudness spread before and after

Be explicit that the scores are a shortlist for listening, not a quality verdict, and
that you cannot hear the audio yourself. Spot-check timestamps are ambiguous by design —
a weakening beat may be an intentional breakdown.

$ARGUMENTS
