---
description: Render a screened playlist into an uploadable video with titles and a waveform
---

Render the playlist into a finished video.

Read `docs/07-rendering-the-video.md` first — it carries the traps that cost a rendering
pass each (the waveform needs an alpha mask, the pad colour must come from the cover, a
preview seek shifts the title timeline).

1. Confirm the playlist folder exists. It is the `playlist/` written by
   `run.py --export`; without `--export` there is nothing numbered to render.
2. Ask for the cover image if the user has not named one. Do **not** generate an image
   without being asked — it may spend the user's credits.
3. Render a preview across a track boundary first and look at it:

   ```bash
   python3 tools/track-picker/render.py --playlist <dir> --cover <img> --out <out> \
     --preview 8 --preview-at <boundary> --preset ultrafast
   ```

   Get the boundary from the timestamps file. Check three things in the frames: the
   title changes at the boundary, the wave is visible against the cover, and the title
   is not struck through by the wave.
4. Then render in full and hand over both the MP4 and the description file.

You cannot hear the audio. Everything above is checked by looking at frames and by
measuring — never claim the result sounds right.
