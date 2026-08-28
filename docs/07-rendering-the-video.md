# Rendering the video

The screened, sequenced playlist is audio and a folder of filenames. This turns it into
one uploadable MP4: the cover held for the whole runtime, the current track's number and
title in the lower left, and a waveform along the bottom that moves with the audio.

```bash
python3 tools/track-picker/render.py \
  --playlist ./ep06/playlist --cover cover.png --out ./ep06 --name ep06
```

It writes `ep06.mp4` and `ep06_description.txt` (chapter timestamps, ready to paste).

## Preview before you commit an hour

A full render of a 56-minute episode is minutes of encoding. `--preview` renders a short
window instead, and `--preview-at` seeks to the moment worth checking — almost always a
track boundary, because that is where the cross-fade either works or does not.

```bash
python3 tools/track-picker/render.py ... --preview 8 --preview-at 152 --preset ultrafast
```

The seek is the subtle part. `-ss` restarts the output timeline at zero while the title
spans are absolute, so a preview shifts every span by `--preview-at`. Without that shift
a preview shows no titles at all and looks like a rendering bug rather than a seek bug.

## Three things that are not obvious

**The waveform has to be drawn as an alpha mask.** `showwaves` draws on an opaque black
background. Overlaying its output directly paints a black band across the cover — the
wave is there, invisible against black. Render the wave white, take it as a luminance
mask, and merge it onto a flat colour:

```
[1:a]volume=3,showwaves=s=1920x130:mode=cline:colors=white,format=gray[wm];
color=c=<accent>:s=1920x130[wc];
[wc][wm]alphamerge,colorchannelmixer=aa=0.75[wave]
```

**Pad with the cover's own paper colour.** ffmpeg pads with black. A cream illustration
that is not exactly 16:9 comes back framed in mourning bars.

**Sample the overlay colours from the cover.** On the illustrated covers this playbook
produces, the paper is usually the single largest colour in the frame — measured at 84%
of one cover. White text on that is invisible, and a neon spectrum fights hand-drawn art.
`render.py` quantises the cover, takes the most common cluster as paper, the darkest
remaining cluster as ink, and the most saturated (weighted by area) as accent.
`--ink` / `--accent` / `--paper` override it.

## Waveform gain

`showwaves` maps full scale to the box height, and a playlist normalised to about
−19 LUFS never approaches full scale, so the wave sits nearly flat at unity gain. The
gain is visual only — it is applied to a copy of the audio feeding the filter, never to
the audio that is muxed.

| Gain | Wave height at −21.7 dB | Verdict |
|---|---|---|
| 3 | 149px of a 178px box | headroom left for louder passages |
| 6 | 178px (clipped to the box) | flattens loud and quiet into one shape |

`WAVE_GAIN = 3.0`. Measured at −56.6 dB — the tail of a fade-out — the wave goes flat,
which is correct and not a defect: track boundaries land in near-silence, so the wave
naturally rests exactly when the title changes.

## The waveform is 78% of the file

Measured on the same 60-second window, `veryfast`, CRF 20:

| Render | Bitrate |
|---|---|
| Cover + titles + wave | 2.67 Mbps |
| Cover + wave, no titles | 2.66 Mbps |
| Cover + titles, no wave | 0.58 Mbps |

The titles cost nothing — they change 20 times in an hour. The wave is redrawn every
frame from a different 40 ms window, so consecutive frames are uncorrelated and the codec
has nothing to predict from. That is the worst case for inter-frame compression.

Drawing the wave narrow and scaling it up cuts both the bitrate and the crispness:

| `--wave-detail` | Bitrate | Look |
|---|---|---|
| 1920 | 2.67 Mbps | crisp — an instrument readout |
| 480 | 1.87 Mbps | soft-edged, brushstroke-like |
| 240 | 1.65 Mbps | smeared, loses definition |

`WAVE_DETAIL = 480` is the default: on illustrated covers the softer wave suits the
artwork better than the sharp one, and it happens to be 30% smaller.

## The title must clear the wave box

The wave fills its **whole box** at full amplitude, so the box top, not the resting line
at its centre, is what the title has to clear. On a first render the title sat inside the
band and loud passages struck it through.

Measured on a rendered frame by differencing against a cover-only frame — the only way to
tell overlay pixels from the illustration's own dark pixels:

| Element | Rows occupied |
|---|---|
| Title block | 780–862 |
| Wave box | 931–1060 |

`layout()` derives every position from the frame height and a test asserts the gap holds
at 720p through 4K, because both values scale and the collision returns silently.

## Chapter timestamps

The audio is concatenated with `-c copy`, so the timestamps computed at export time land
exactly: verified against a rendered episode, the audio inside the MP4 matched the source
at correlation 1.0000 at the first, middle and last chapter.

The joined intermediate is deleted after a successful render — an hour of wav export is
about 640 MB, and re-joining it with `-c copy` takes under a second. `--keep-audio` keeps
it.

One catch: `--export-format wav` writes PCM, which has no tag in an MP4 container.
Concatenating a wav export into `.m4a` fails outright with *"Could not find tag for codec
pcm_s16le"*. The intermediate container follows the source extension.
