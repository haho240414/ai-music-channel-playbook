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

**Sample the overlay colours from the cover — and check them.** On the illustrated covers this playbook
produces, the paper is usually the single largest colour in the frame — measured at 84%
of one cover. White text on that is invisible, and a neon spectrum fights hand-drawn art.
Sampling alone guarantees nothing, though. See the next section.
`--ink` / `--accent` / `--paper` override it.

## A palette that only works on light covers is half a palette

The first version assumed the artwork was light: it took the darkest cluster as ink and
deepened it. Run across six covers — three watercolours on cream, three night
photographs — the three dark ones came back at **1.1:1, 1.1:1 and 1.5:1**. Body text
wants 4.5:1. The titles were not dim; they were not there.

Three things fix it, and each is a measurement rather than a rule of thumb.

**Decide polarity from where the text actually goes.** Not from the frame's dominant
colour — that tells you what the picture is mostly made of, not what is behind the
title. `sample_colors` averages the strip the text occupies and picks ink from the
direction that can reach contrast there.

**Then force the contrast.** A colour lifted out of the artwork keeps the palette honest
and promises nothing, so ink is blended toward white or black until it clears its floor.
Title 7:1, label 3:1.

**Give the wave a different floor from the label.** They shared the accent at first, and
holding the wave to a text threshold darkened a colour taken straight from the artwork —
a validated `0xD09050` became `0xBB8248`. The wave is a graphic, not text: its floor
(1.6) only rules out a wave nobody can see.

| Cover | Ink | Title contrast |
|---|---|---|
| watercolour on cream | `0x59321E` | 10.3:1 |
| night street | `0xF6F6E2` | 13.0:1 |
| dusk bridge | `0xF6F6F6` | 12.1:1 |

**On dark art the accent is the light in the picture.** Weighted by area, the biggest
saturated cluster in a night photograph is a murky sky, and lifting that for contrast
only greys it. Weighting brightness in and easing the area term off (exponent 0.15
rather than 0.5) picks the streetlights instead — `0xF0B030` on the dusk cover.

**A shadow, because an average is not a guarantee.** Contrast is measured against the
mean of the title area, but a photograph is not uniform: a lit window directly behind
the small label erases it while the average still passes. The shadow is drawn in the
opposite polarity to the text and does not depend on the average.

**Put the text on the calmer half.** On one cover the lower-left sat on a row of
streetlights while the lower-right was open water that varied a third as much
(σ 0.021 against 0.074). `pick_text_side` compares the two halves and takes the steadier
one; ties keep the left, so a channel stays consistent between episodes.

## Three shapes, and they are not interchangeable

`--wave-style` picks what the visualiser draws:

- `wave` — mirrored waveform, the default
- `bars` — the same amplitude quantised into blocks
- `spectrum` — a frequency equaliser, bars rising from a baseline

Bar styles need nearest-neighbour scaling (bicubic rounds the column edges straight back
off) plus a `geq` stripe that blanks part of every slot, or the blocks touch and read as
a solid wave again.

`spectrum` needs `ascale=log`, and finding that out took four passes. On a linear or
sqrt amplitude axis every bar past the first few collapses into a flat dashed line. That
is not a bug: music really does put nearly all of its energy in the low octaves. A dB
axis spreads it into the equaliser people expect.

Measured over the same passage, same metric as the smoothing section:

| Style | Painted area | Response | Jitter |
|---|---|---|---|
| `wave` | 21.8% | 6.49 | 2.18 |
| `bars` | 15.2% | 5.26 | 1.72 |
| `spectrum` | 39.5% | 1.02 | 0.26 |

`spectrum` fills 2.6× more of the band than `bars` while responding to the music 5× less.
The dB axis that makes it look like an equaliser is the same thing that flattens its
dynamics, so it settles into a near-fixed spectral silhouette: busy to look at, saying
little. Its ratio of response to jitter is the best of the three, which is the same trap
a sparse `p2p` wave set earlier — a ratio flatters anything that barely moves. `bars`
keeps the waveform's responsiveness and still reads as bars.

## Matching the wave to the channel

`--wave-detail` and `--wave-smooth` are not taste settings. Crisp detail earns its place
only when the frame-to-frame change is music rather than noise, and that is exactly what
the screener already measures per track as **pulse clarity**. Across six channels it
ranged from 0.375 to 0.711 — nearly a factor of two.

So both settings are derived from the median pulse clarity of the episode, anchored on
the one combination checked frame by frame (0.377 → detail 160, smooth 6):

```
detail = clamp(160 × pulse / 0.377, 120, 480)
smooth = clamp(6 × 0.377 / pulse,     3,  10)
```

| Channel type | Pulse | Detail | Smooth |
|---|---|---|---|
| loose, ambient | 0.375 | 159 | 6 |
| mid | 0.403 | 171 | 6 |
| steady beat | 0.531 | 225 | 4 |
| strong beat | 0.711 | 302 | 3 |

Music with a strong pulse can carry an articulate wave, because what the wave shows is
the beat. Loose, ambient material cannot: drawn sharply it shows noise, so it gets fewer
columns and more averaging.

## Waveform gain

`showwaves` maps full scale to the box height, and a playlist normalised to about
−19 LUFS never approaches full scale, so the wave sits nearly flat at unity gain. The
gain is visual only — it is applied to a copy of the audio feeding the filter, never to
the audio that is muxed.

| Gain | Wave height at −21.7 dB | Verdict |
|---|---|---|
| 3 | 149px of a 178px box | headroom left for louder passages |
| 6 | 178px (clipped to the box) | flattens loud and quiet into one shape |

`WAVE_GAIN = 3.5` — a little above the 3 that was right before smoothing, because
averaging frames pulls the peaks down. Measured at −56.6 dB — the tail of a fade-out — the wave goes flat,
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

`WAVE_DETAIL = 160`, below this table's range, because detail alone is not what makes a
wave restless — see the next section.

## Half the motion was not music

Drawn one frame at a time the wave jumps around in a way that reads as noise rather than
as the track. Split the movement in two: how much the painted area varies across the
whole passage (that is the music) against how much it changes between adjacent frames
(that is jitter). Their ratio says how much of the motion means something.

| Setting | Response | Jitter | Ratio |
|---|---|---|---|
| 480, no smoothing | 6.21 | 5.68 | 1.1 |
| 480, 6 frames | 4.00 | 1.63 | 2.4 |
| 480, 14 frames | 4.05 | 1.17 | 3.5 |
| p2p, 6 frames | 3.92 | 0.67 | 5.8 |
| **160, 6 frames** | **3.95** | **1.59** | **2.5** |

At the default the ratio was 1.1: half of what the eye saw was per-frame noise.

Two of these were rejected on looks despite scoring well, which is the point of checking
frames and not only numbers. `p2p` won the ratio by drawing almost nothing — 2% coverage,
a wave too faint to see. Fourteen frames of averaging dissolves the strokes into a haze
that no longer reads as a waveform. Adding a gaussian blur on top of heavy averaging
flattened it to a bare line.

`WAVE_SMOOTH = 6` with `WAVE_DETAIL = 160`: painted area 23.2% against 24.2% unsmoothed —
the same visual weight — with jitter down from 5.68 to 1.75, a 69% reduction.

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
