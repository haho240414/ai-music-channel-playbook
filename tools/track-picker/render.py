#!/usr/bin/env python3
"""Render a screened playlist into an uploadable video.

Takes the `playlist/` folder written by `run.py --export` plus one cover image, and
produces a single MP4: the cover held for the whole runtime, the current track's
number and title in the lower left, and an audio-reactive waveform along the bottom.

    python3 render.py --playlist ./ep06/playlist --cover cover.png --out ./ep06

Three things here are deliberate, and each cost a rendering pass to learn:

- **The waveform is drawn as an alpha mask, not overlaid directly.** `showwaves` draws
  on an opaque black background; overlaying that on a light cover paints a black band
  across the frame. Rendering the wave in white, taking it as a luminance mask and
  merging it onto a flat colour keeps only the strokes.
- **The pad colour is sampled from the cover's own corner.** ffmpeg pads with black by
  default, which frames a cream illustration in mourning bars.
- **The overlay colours are sampled from the cover too** (`--ink`/`--accent` override).
  A white title is invisible on a light cover, and a neon spectrum fights hand-drawn art.

The audio is concatenated without re-encoding, so the chapter timestamps computed at
export time land exactly.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analyze import FFMPEG, ffmpeg_available  # noqa: E402

VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv")
AUDIO_EXT = (".m4a", ".mp3", ".wav", ".flac")

# Fonts that ship with macOS; the first that exists wins. A serif suits illustrated
# covers better than the sans a default drawtext call would pick.
TITLE_FONTS = [
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/System/Library/Fonts/Supplemental/Baskerville.ttc",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
LABEL_FONTS = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
] + TITLE_FONTS

FADE = 0.9          # seconds of cross-fade on the title at each track change
WAVE_GAIN = 3.5     # visual only: lifts the wave so quiet passages still move
WAVE_DETAIL = 160   # px the wave is drawn at before being scaled up; see docs/07
WAVE_SMOOTH = 6     # frames averaged together to settle the wave; see docs/07
WAVE_STYLE = "wave"  # wave | bars | spectrum; see docs/07
BAR_GAP = 0.27       # share of each bar's slot left empty, for the bars styles


def pick_text_side(cover: str, width: int, height: int, paper: str) -> str:
    """Put the text on the calmer half of the frame.

    Contrast against an average is not enough on a photograph: measured on one cover the
    lower-left sat directly on a row of streetlights and washed the label out, while the
    lower-right (open water) varied a third as much. Compare the two halves of the strip
    the text occupies and take the steadier one; ties keep the left, which is the
    convention and keeps a channel consistent across episodes.
    """
    base = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={paper}")
    spread = {}
    for side, x in (("left", 0), ("right", int(width * 0.42))):
        px = _pixels(cover, f"{base},crop={int(width*0.58)}:{int(height*0.11)}:{x}:"
                            f"{int(height*0.71)},scale=48:10")
        if not px:
            return "left"
        lum = [_srgb_lum(c) for c in px]
        mean = sum(lum) / len(lum)
        spread[side] = (sum((v - mean) ** 2 for v in lum) / len(lum)) ** 0.5
    return "right" if spread["right"] < spread["left"] * 0.75 else "left"


def layout(width: int, height: int, title_size: int, wave_h: int,
           side: str = "left") -> dict:
    """Where each element sits. Kept in one place so the no-overlap rule is testable.

    The wave fills its whole box at full amplitude, so the box top -- not the resting
    line at its centre -- is what the title has to clear.
    """
    margin = int(width * 0.068)
    return {
        # A right-aligned line has to be positioned from the text width, which drawtext
        # only knows at draw time -- hence an expression rather than a number.
        "x": str(margin) if side == "left" else f"w-tw-{margin}",
        "y_label": int(height * 0.723),
        "y_title": int(height * 0.764),
        "title_bottom": int(height * 0.764) + title_size,
        "wave_top": height - wave_h - int(height * 0.019),
        "wave_bottom": height - int(height * 0.019),
    }


def _run(cmd: list[str]) -> None:
    # stdin is closed deliberately: ffmpeg reads stdin for interactive keys, and inside
    # a `while read ... done < list.txt` loop over several channels it swallows the
    # loop's own input, truncating the next channel's name.
    p = subprocess.run(cmd, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise SystemExit(f"ffmpeg failed:\n{p.stderr.decode(errors='ignore')[-2000:]}")


def first_font(candidates: list[str]) -> str:
    for f in candidates:
        if os.path.exists(f):
            return f
    raise SystemExit("no usable font found -- pass --title-font with a .ttf/.ttc path")


def ordered_tracks(playlist_dir: str) -> list[str]:
    """Tracks in play order. Export numbers them, so filename order IS play order."""
    names = [n for n in sorted(os.listdir(playlist_dir))
             if os.path.splitext(n)[1].lower() in AUDIO_EXT]
    if not names:
        raise SystemExit(f"no audio found in {playlist_dir} -- run with --export first")
    return [os.path.join(playlist_dir, n) for n in names]


def duration_of(path: str) -> float:
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", path],
                         stdin=subprocess.DEVNULL,
                         stderr=subprocess.PIPE).stderr.decode(errors="ignore")
    m = re.search(r"Duration:\s*(\d+):(\d\d):(\d\d\.\d+)", out)
    if not m:
        raise SystemExit(f"could not read duration of {path}")
    h, mm, s = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(s)


def title_of(path: str) -> str:
    """Recover the display title from an exported filename (`01_Azure_Breeze.wav`)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"^\d+[_\-\s]+", "", stem).replace("_", " ").strip() or stem


def _srgb_lum(rgb) -> float:
    def ch(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    """WCAG contrast ratio between two RGB tuples."""
    la, lb = _srgb_lum(a), _srgb_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def force_contrast(fg, bg, target: float):
    """Blend fg toward white or black until it reads against bg.

    Sampling a colour out of the artwork keeps the palette honest but guarantees
    nothing: on a night photograph the darkest cluster is nearly black, and putting
    it on a near-black background measured 1.1:1 -- text that is simply not there.
    """
    toward = (255, 255, 255) if _srgb_lum(bg) < 0.18 else (0, 0, 0)
    best = tuple(fg)
    for i in range(1, 21):
        if contrast(best, bg) >= target:
            return best
        t = i / 20.0
        best = tuple(int(round(f + (w - f) * t)) for f, w in zip(fg, toward))
    return best


def _pixels(cover: str, vf: str):
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", cover, "-vf", vf,
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    return [tuple(raw[i:i + 3]) for i in range(0, len(raw) - 2, 3)]


def sample_colors(cover: str, width: int = 1920, height: int = 1080
                  ) -> tuple[str, str, str, str]:
    """Read the cover's own palette: (paper, ink, accent) as ffmpeg hex.

    Two measurements, not one. The palette comes from the whole image, but whether the
    text should be dark or light is decided by the area the text actually sits in --
    a night photograph and a watercolour on cream need opposite answers, and the
    dominant colour of the frame does not tell you which you have.
    """
    px = _pixels(cover, "scale=160:90")
    if len(px) < 8:
        return "0xF2EFE6", "0x3A2A20", "0xC07840", "0xC07840"
    quant = collections.Counter(tuple(c // 32 * 32 + 16 for c in p) for p in px)
    paper = quant.most_common(1)[0][0]

    # The band the title and the wave live in: bottom third, left of centre.
    scale = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
             f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x%02X%02X%02X" % paper)
    band = _pixels(cover, f"{scale},crop={int(width*0.75)}:{int(height*0.27)}:0:"
                          f"{int(height*0.72)},scale=40:12")
    bg = tuple(sum(c[i] for c in band) // len(band) for i in range(3)) if band else paper

    far = [(c, n) for c, n in quant.items()
           if sum(abs(a - b) for a, b in zip(c, paper)) > 60]
    if not far:
        far = list(quant.items())
    dark_bg = _srgb_lum(bg) < 0.18
    # Pick from the artwork in the direction that can actually reach contrast.
    ink = (max(far, key=lambda x: sum(x[0])) if dark_bg
           else min(far, key=lambda x: sum(x[0])))[0]
    # Deepen (or lift) it before measuring. The darkest cluster in watercolour is still
    # mid-tone, and title text wants more weight than the drawing itself carries.
    pull = 255 if dark_bg else 0
    ink = tuple(int(round(c + (pull - c) * 0.38)) for c in ink)
    sat = lambda c: (max(c) - min(c)) / max(max(c), 1)  # noqa: E731
    # On a night photograph the most saturated large cluster is a murky blue, and
    # lifting that for contrast only greys it further. What reads on a dark frame is
    # the light in it -- the lamp, the streetlights -- so weight by brightness too.
    # The frequency term is weaker on dark art on purpose: streetlights and a desk lamp
    # cover few pixels but are what the eye reads, while the sky covers most of the frame
    # and lifting it for contrast only yields grey.
    weight = ((lambda c: sat(c) * _srgb_lum(c) ** 0.5) if dark_bg else sat)
    freq_exp = 0.15 if dark_bg else 0.5
    accent = max(far, key=lambda x: weight(x[0]) * (x[1] ** freq_exp))[0]

    ink = force_contrast(ink, bg, 7.0)  # title: AAA, and a richer ink on light art
    # The wave and the label take different floors. The label is text and needs 3:1; the
    # wave is a graphic, and holding it to a text threshold darkened a colour lifted
    # straight out of the artwork. 1.6 only rules out a wave you cannot see at all.
    label = force_contrast(accent, bg, 3.0)
    wave = force_contrast(accent, bg, 1.6)
    return ("0x%02X%02X%02X" % paper, "0x%02X%02X%02X" % ink,
            "0x%02X%02X%02X" % wave, "0x%02X%02X%02X" % label)


def concat_container(tracks: list[str], stem: str) -> str:
    """Pick a container the source codec actually fits.

    `--export-format wav` writes PCM, and PCM has no tag in an MP4/ipod container, so
    concatenating into `.m4a` fails outright. Reusing the source extension keeps the
    stream copyable whatever format was exported.
    """
    exts = {os.path.splitext(t)[1].lower() for t in tracks}
    ext = exts.pop() if len(exts) == 1 else ".mkv"  # mixed input: a container that takes anything
    return stem + ext


def concat_audio(tracks: list[str], out_path: str) -> str:
    """Join without re-encoding where possible, so the chapter grid cannot shift."""
    listing = out_path + ".txt"
    with open(listing, "w", encoding="utf-8") as f:
        for t in tracks:
            f.write("file '%s'\n" % os.path.abspath(t).replace("'", r"'\''"))
    _run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
          "-i", listing, "-c", "copy", out_path])
    os.remove(listing)
    return out_path


def spans(tracks: list[str]) -> list[tuple[int, str, float, float]]:
    """(position, title, start, end) for every track, in play order."""
    out, t = [], 0.0
    for i, path in enumerate(tracks, 1):
        d = duration_of(path)
        out.append((i, title_of(path), t, t + d))
        t += d
    return out


def esc(text: str) -> str:
    """Escape text for a drawtext filter argument."""
    return (text.replace("\\", r"\\").replace(":", r"\:")
                .replace("'", r"\'").replace("%", r"\%")
                .replace("[", r"\[").replace("]", r"\]").replace(",", r"\,"))


def shadow_for(ink: str) -> str:
    """A shadow in the opposite polarity to the text.

    Contrast is measured against the average of the title area, but a photograph is not
    uniform: a streetlight or a lit window right behind the label erases it even when
    the average passes. A shadow does not depend on the average.
    """
    rgb = (int(ink[2:4], 16), int(ink[4:6], 16), int(ink[6:8], 16))
    return "black@0.55" if _srgb_lum(rgb) > 0.4 else "white@0.45"


def title_filters(items, width, height, ink, accent, title_font, label_font,
                  title_size, label_size, offset: float = 0.0,
                  side: str = "left", label_col: str = None) -> list[str]:
    """One label+title pair per track, cross-fading into the next.

    The fade is an alpha ramp rather than two overlapping clips: drawtext is evaluated
    per frame, so a ramp costs nothing and cannot drift out of sync with the audio.
    """
    # The text sits ABOVE the wave band, not inside it. At full amplitude the wave
    # reaches the top of its box, and a title placed over it gets struck through.
    geo = layout(width, height, title_size, 0, side)
    x, y_label, y_title = geo["x"], geo["y_label"], geo["y_title"]
    total = len(items)
    out = []
    for pos, title, start, end in items:
        # A preview seeks the audio with -ss, so the output timeline restarts at zero
        # while these spans are absolute. Without the shift every title in a preview
        # renders at the wrong time -- or not at all.
        start, end = start - offset, end - offset
        if end <= 0:
            continue
        start = max(start, 0.0)
        # Hold full opacity in the middle, ramp at both ends. Guard against a track
        # shorter than two fades, which would otherwise invert the ramp.
        f = min(FADE, max((end - start) / 2.5, 0.05))
        alpha = (f"if(lt(t,{start + f:.3f}),(t-{start:.3f})/{f:.3f},"
                 f"if(gt(t,{end - f:.3f}),({end:.3f}-t)/{f:.3f},1))")
        window = f"between(t,{start:.3f},{end:.3f})"
        sh = shadow_for(ink)
        common = (f":enable='{window}':alpha='{alpha}':x={x}"
                  f":shadowcolor={sh}:shadowx=2:shadowy=2")
        out.append(
            f"drawtext=fontfile='{label_font}':text='{esc('TRACK %02d OF %02d' % (pos, total))}'"
            f":fontsize={label_size}:fontcolor={label_col or accent}{common}:y={y_label}")
        out.append(
            f"drawtext=fontfile='{title_font}':text='{esc(title)}'"
            f":fontsize={title_size}:fontcolor={ink}{common}:y={y_title}")
    return out


def wave_mask(width: int, wave_h: int, detail: int, smooth: int,
              style: str = WAVE_STYLE) -> str:
    """The filter chain producing a white-on-black mask of the visualisation.

    Three shapes, and they are not interchangeable:

    - `wave`     mirrored waveform, the calm default
    - `bars`     the same amplitude quantised into blocks
    - `spectrum` a frequency equaliser, bars rising from the baseline

    `spectrum` needs `ascale=log`. Music puts most of its energy in the low octaves, so
    on a linear or sqrt amplitude axis every bar past the first few collapses into a
    flat dashed line -- it looks broken, and it is not: it is what the spectrum of this
    material actually is. A dB axis spreads it into the equaliser people expect.
    """
    smoothing = f",tmix=frames={smooth}" if smooth > 1 else ""
    if style == "spectrum":
        # averaging is showfreqs' own temporal smoothing; tmix on top would double it.
        src = (f"volume={WAVE_GAIN},showfreqs=s={detail}x{wave_h}:mode=bar"
               f":ascale=log:fscale=log:win_size=4096:averaging={max(smooth, 1)}"
               f":colors=white,format=gray")
    else:
        src = (f"volume={WAVE_GAIN},showwaves=s={detail}x{wave_h}:mode=cline"
               f":colors=white:rate=25,format=gray{smoothing}")
    if style == "wave":
        return f"{src},scale={width}:{wave_h}:flags=bicubic"
    # Blocks: nearest-neighbour keeps the column edges hard, then a stripe expression
    # blanks part of every slot so the blocks read as separate bars.
    slot = max(int(round(width / max(detail, 1))), 3)
    keep = max(int(round(slot * (1 - BAR_GAP))), 2)
    return (f"{src},scale={width}:{wave_h}:flags=neighbor,"
            + r"geq=lum='if(lt(mod(X\," + str(slot) + r")\," + str(keep)
            + r")\,p(X\,Y)\,0)'")


def build_filtergraph(cover, items, width, height, paper, ink, accent,
                      title_font, label_font, title_size, label_size,
                      wave_h, wave_alpha, is_video, offset: float = 0.0,
                      detail: int = WAVE_DETAIL, smooth: int = WAVE_SMOOTH,
                      side: str = "left", label_col: str = None,
                      style: str = WAVE_STYLE) -> str:
    scale = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
             f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={paper},setsar=1")
    wave_y = height - wave_h - int(height * 0.019)
    parts = [
        f"[0:v]{scale}[bg]",
        # White wave -> luminance mask -> tint. Overlaying showwaves directly would
        # paint its opaque black background across the cover.
        # Drawn narrow, averaged over several frames, then scaled up. At full width and
        # one frame the wave is a crisp instrument readout: it costs 78% of the file and
        # half its motion is per-frame noise rather than music. See docs/07.
        f"[1:a]{wave_mask(width, wave_h, detail, smooth, style)}[wm]",
        f"color=c={accent}:s={width}x{wave_h}:r=25[wc]",
        f"[wc][wm]alphamerge,colorchannelmixer=aa={wave_alpha}[wave]",
        f"[bg][wave]overlay=0:{wave_y}:shortest={1 if is_video else 0}[v0]",
    ]
    chain = ",".join(title_filters(items, width, height, ink, accent,
                                   title_font, label_font, title_size, label_size,
                                   offset, side, label_col))
    parts.append(f"[v0]{chain}[v]" if chain else "[v0]null[v]")
    return ";".join(parts)


def chapter_lines(items) -> list[str]:
    lines = []
    for pos, title, start, _ in items:
        h, rem = divmod(int(start), 3600)
        m, s = divmod(rem, 60)
        stamp = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        lines.append(f"{stamp} {title}")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--playlist", required=True,
                    help="the playlist/ folder written by run.py --export")
    ap.add_argument("--cover", required=True, help="cover image, or a short video to loop")
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--name", default="episode")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--preset", default="veryfast")
    ap.add_argument("--ink", help="title colour (default: sampled from the cover)")
    ap.add_argument("--accent", help="wave and label colour (default: sampled)")
    ap.add_argument("--paper", help="letterbox colour (default: sampled)")
    ap.add_argument("--title-font"), ap.add_argument("--label-font")
    ap.add_argument("--title-size", type=int, default=0, help="0 = scale to height")
    ap.add_argument("--label-size", type=int, default=0)
    ap.add_argument("--wave-height", type=int, default=0)
    ap.add_argument("--wave-alpha", type=float, default=0.75)
    ap.add_argument("--wave-detail", type=int, default=WAVE_DETAIL,
                    help="px the wave is drawn at before scaling up; lower is softer "
                         "and smaller (1920 = crisp instrument readout)")
    ap.add_argument("--wave-style", choices=("wave", "bars", "spectrum"),
                    default=WAVE_STYLE,
                    help="wave = mirrored waveform, bars = the same amplitude as "
                         "blocks, spectrum = a frequency equaliser")
    ap.add_argument("--text-side", choices=("auto", "left", "right"), default="auto",
                    help="which half of the frame the title sits in")
    ap.add_argument("--wave-smooth", type=int, default=WAVE_SMOOTH,
                    help="frames averaged together; 1 disables, higher is calmer but "
                         "dissolves the wave into a smudge past about 10")
    ap.add_argument("--no-wave", action="store_true")
    ap.add_argument("--no-titles", action="store_true")
    ap.add_argument("--keep-audio", action="store_true",
                    help="keep the concatenated intermediate (a wav export of an hour "
                         "is ~640 MB; re-joining it costs under a second)")
    ap.add_argument("--preview", type=float, default=0,
                    help="render only N seconds, starting at --preview-at")
    ap.add_argument("--preview-at", type=float, default=0)
    args = ap.parse_args()

    if not ffmpeg_available():
        raise SystemExit(f"ffmpeg is required but could not be run (tried: {FFMPEG}).")
    if not os.path.exists(args.cover):
        raise SystemExit(f"cover not found: {args.cover}")

    os.makedirs(args.out, exist_ok=True)
    tracks = ordered_tracks(args.playlist)
    items = spans(tracks)
    total = items[-1][3]
    print(f"[1/4] {len(tracks)} tracks, {int(total // 60)}m {int(total % 60)}s")

    paper, ink, accent, label_col = sample_colors(args.cover, args.width, args.height)
    paper, ink = args.paper or paper, args.ink or ink
    if args.accent:
        accent = label_col = args.accent
    print(f"[2/4] palette from cover: paper {paper}  ink {ink}  "
          f"wave {accent}  label {label_col}")

    audio = concat_container(tracks, os.path.join(args.out, f"{args.name}_audio"))
    concat_audio(tracks, audio)

    title_font = args.title_font or first_font(TITLE_FONTS)
    label_font = args.label_font or first_font(LABEL_FONTS)
    title_size = args.title_size or max(int(args.height * 0.050), 12)
    label_size = args.label_size or max(int(args.height * 0.019), 9)
    wave_h = args.wave_height or int(args.height * 0.120)
    is_video = os.path.splitext(args.cover)[1].lower() in VIDEO_EXT

    side = (pick_text_side(args.cover, args.width, args.height, paper)
            if args.text_side == "auto" else args.text_side)
    print(f"       text on the {side}")
    graph = build_filtergraph(args.cover, items, args.width, args.height,
                              paper, ink, accent, title_font, label_font,
                              title_size, label_size, wave_h, args.wave_alpha,
                              is_video, args.preview_at, args.wave_detail,
                              args.wave_smooth, side, label_col, args.wave_style)
    if args.no_wave or args.no_titles:
        graph = build_filtergraph(args.cover, [] if args.no_titles else items,
                                  args.width, args.height, paper, ink, accent,
                                  title_font, label_font, title_size, label_size,
                                  wave_h, 0.0 if args.no_wave else args.wave_alpha,
                                  is_video, args.preview_at, args.wave_detail,
                              args.wave_smooth, side, label_col, args.wave_style)

    video = os.path.join(args.out, f"{args.name}.mp4")
    cmd = [FFMPEG, "-y", "-v", "error"]
    if is_video:
        cmd += ["-stream_loop", "-1", "-i", args.cover]
    else:
        cmd += ["-loop", "1", "-framerate", "25", "-i", args.cover]
    if args.preview_at:
        cmd += ["-ss", str(args.preview_at)]
    cmd += ["-i", audio, "-filter_complex", graph, "-map", "[v]", "-map", "1:a",
            "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
            "-pix_fmt", "yuv420p", "-r", "25",
            "-c:a", "aac", "-b:a", "256k", "-shortest",
            "-movflags", "+faststart"]
    if args.preview:
        cmd += ["-t", str(args.preview)]
    cmd += [video]
    print(f"[3/4] rendering {'preview' if args.preview else 'full video'}")
    _run(cmd)

    desc = os.path.join(args.out, f"{args.name}_description.txt")
    with open(desc, "w", encoding="utf-8") as f:
        f.write("\n".join(chapter_lines(items)) + "\n")
    size = os.path.getsize(video) / 1048576
    if not args.keep_audio and not args.preview:
        try:
            os.remove(audio)
        except OSError:
            pass
    print(f"[4/4] done -> {video}  ({size:.1f} MB)")
    print(f"       {desc}  (paste into the upload form)")


if __name__ == "__main__":
    main()
