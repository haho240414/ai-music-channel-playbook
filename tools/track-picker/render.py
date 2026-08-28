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
WAVE_GAIN = 3.0     # visual only: lifts the wave so quiet passages still move


def layout(width: int, height: int, title_size: int, wave_h: int) -> dict:
    """Where each element sits. Kept in one place so the no-overlap rule is testable.

    The wave fills its whole box at full amplitude, so the box top -- not the resting
    line at its centre -- is what the title has to clear.
    """
    return {
        "x": int(width * 0.068),
        "y_label": int(height * 0.723),
        "y_title": int(height * 0.764),
        "title_bottom": int(height * 0.764) + title_size,
        "wave_top": height - wave_h - int(height * 0.019),
        "wave_bottom": height - int(height * 0.019),
    }


def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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


def sample_colors(cover: str) -> tuple[str, str, str]:
    """Read the cover's own palette: (paper, ink, accent) as ffmpeg hex.

    Guessing these produced white text on a cream background -- invisible. The corner
    is the paper; the darkest non-paper cluster is the ink; the most saturated one,
    weighted by how much of the image it covers, is the accent.
    """
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", cover, "-vf", "scale=160:90",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    if len(raw) < 3:
        return "0xF2EFE6", "0x3A2A20", "0xC07840"
    px = [tuple(raw[i:i + 3]) for i in range(0, len(raw) - 2, 3)]
    quant = collections.Counter(tuple(c // 32 * 32 + 16 for c in p) for p in px)
    paper = quant.most_common(1)[0][0]
    far = [(c, n) for c, n in quant.items()
           if sum(abs(a - b) for a, b in zip(c, paper)) > 60]
    if not far:
        return "0x%02X%02X%02X" % paper, "0x3A2A20", "0xC07840"
    ink = min(far, key=lambda x: sum(x[0]))[0]
    sat = lambda c: (max(c) - min(c)) / max(max(c), 1)  # noqa: E731
    accent = max(far, key=lambda x: sat(x[0]) * (x[1] ** 0.5))[0]
    # Darken the ink a little: the darkest *cluster* is still mid-tone in watercolour,
    # and title text wants more contrast than the drawing itself has.
    ink = tuple(int(c * 0.62) for c in ink)
    return ("0x%02X%02X%02X" % paper, "0x%02X%02X%02X" % ink,
            "0x%02X%02X%02X" % accent)


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


def title_filters(items, width, height, ink, accent, title_font, label_font,
                  title_size, label_size, offset: float = 0.0) -> list[str]:
    """One label+title pair per track, cross-fading into the next.

    The fade is an alpha ramp rather than two overlapping clips: drawtext is evaluated
    per frame, so a ramp costs nothing and cannot drift out of sync with the audio.
    """
    # The text sits ABOVE the wave band, not inside it. At full amplitude the wave
    # reaches the top of its box, and a title placed over it gets struck through.
    geo = layout(width, height, title_size, 0)
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
        common = f":enable='{window}':alpha='{alpha}':x={x}"
        out.append(
            f"drawtext=fontfile='{label_font}':text='{esc('TRACK %02d OF %02d' % (pos, total))}'"
            f":fontsize={label_size}:fontcolor={accent}{common}:y={y_label}")
        out.append(
            f"drawtext=fontfile='{title_font}':text='{esc(title)}'"
            f":fontsize={title_size}:fontcolor={ink}{common}:y={y_title}")
    return out


def build_filtergraph(cover, items, width, height, paper, ink, accent,
                      title_font, label_font, title_size, label_size,
                      wave_h, wave_alpha, is_video, offset: float = 0.0) -> str:
    scale = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
             f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={paper},setsar=1")
    wave_y = height - wave_h - int(height * 0.019)
    parts = [
        f"[0:v]{scale}[bg]",
        # White wave -> luminance mask -> tint. Overlaying showwaves directly would
        # paint its opaque black background across the cover.
        f"[1:a]volume={WAVE_GAIN},showwaves=s={width}x{wave_h}:mode=cline"
        f":colors=white:rate=25,format=gray[wm]",
        f"color=c={accent}:s={width}x{wave_h}:r=25[wc]",
        f"[wc][wm]alphamerge,colorchannelmixer=aa={wave_alpha}[wave]",
        f"[bg][wave]overlay=0:{wave_y}:shortest={1 if is_video else 0}[v0]",
    ]
    chain = ",".join(title_filters(items, width, height, ink, accent,
                                   title_font, label_font, title_size, label_size,
                                   offset))
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
    ap.add_argument("--no-wave", action="store_true")
    ap.add_argument("--no-titles", action="store_true")
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

    paper, ink, accent = sample_colors(args.cover)
    paper, ink, accent = args.paper or paper, args.ink or ink, args.accent or accent
    print(f"[2/4] palette from cover: paper {paper}  ink {ink}  accent {accent}")

    audio = concat_container(tracks, os.path.join(args.out, f"{args.name}_audio"))
    concat_audio(tracks, audio)

    title_font = args.title_font or first_font(TITLE_FONTS)
    label_font = args.label_font or first_font(LABEL_FONTS)
    title_size = args.title_size or max(int(args.height * 0.050), 12)
    label_size = args.label_size or max(int(args.height * 0.019), 9)
    wave_h = args.wave_height or int(args.height * 0.120)
    is_video = os.path.splitext(args.cover)[1].lower() in VIDEO_EXT

    graph = build_filtergraph(args.cover, items, args.width, args.height,
                              paper, ink, accent, title_font, label_font,
                              title_size, label_size, wave_h, args.wave_alpha,
                              is_video, args.preview_at)
    if args.no_wave or args.no_titles:
        graph = build_filtergraph(args.cover, [] if args.no_titles else items,
                                  args.width, args.height, paper, ink, accent,
                                  title_font, label_font, title_size, label_size,
                                  wave_h, 0.0 if args.no_wave else args.wave_alpha,
                                  is_video, args.preview_at)

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
    print(f"[4/4] done -> {video}  ({size:.1f} MB)")
    print(f"       {desc}  (paste into the upload form)")


if __name__ == "__main__":
    main()
