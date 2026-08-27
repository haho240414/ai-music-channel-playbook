"""Final deliverables: loudness normalization, numbered files, M3U, and timestamps.

A report alone does not finish an episode. Measured across one batch, LUFS varied by
3.6 LU between tracks -- enough that a listener reaches for the volume between them.

Normalization uses plain gain rather than a dynamics processor (`loudnorm` and friends).
Matching level without touching the mix is the right trade for music; the true-peak
ceiling is respected by reducing gain instead of limiting.
"""
from __future__ import annotations

import os
import re
import subprocess

from analyze import FFMPEG

TARGET_LUFS = -14.0   # common streaming reference
TP_CEILING = -1.0     # dBTP ceiling


def _safe(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip()
    return re.sub(r"\s+", "_", name)[:60] or "track"


def plan_gains(playlist, target=TARGET_LUFS, ceiling=TP_CEILING):
    """Find one common loudness target that every track can actually reach.

    Raising each track toward a fixed target barely helps: AI-generated tracks arrive
    already peak-limited near full scale, so the gain hits the true-peak ceiling and gets
    clamped by a different amount per track. Measured result: 3.6 LU spread became
    3.3 LU. The spread survives.

    Instead, compute the highest LUFS each track could reach without exceeding the
    ceiling, and take the minimum across the episode as the common target.

    The safety invariant is per-track, not a sign check: for every track,
    gain_i = common - lufs_i <= achievable_i - lufs_i = ceiling - tp_i, so the resulting
    true peak can never exceed the ceiling. Most gains come out negative; the track that
    *sets* the minimum gets a small positive gain if it had peak headroom, which is both
    intended and safe. Every track lands at the same loudness (measured: 0.10 LU spread).

    The absolute level ends up below the streaming reference, which does not matter --
    platforms normalize playback loudness anyway.
    """
    achievable = []
    for t in playlist:
        lufs = t["loudness"].get("lufs")
        tp = t["loudness"].get("true_peak")
        if lufs is None:
            continue
        headroom = (ceiling - float(tp)) if tp is not None else 0.0
        achievable.append(float(lufs) + headroom)

    if not achievable:
        return target, {}

    common = min(min(achievable), target)
    gains = {}
    for t in playlist:
        lufs = t["loudness"].get("lufs")
        gains[id(t)] = 0.0 if lufs is None else round(common - float(lufs), 2)
    return round(common, 2), gains


def _encode_args(fmt: str):
    if fmt == "wav":
        return ["-c:a", "pcm_s16le"], ".wav"
    if fmt == "flac":
        return ["-c:a", "flac"], ".flac"
    return ["-c:a", "aac", "-b:a", "256k"], ".m4a"


def export_playlist(playlist, out_dir, fmt="m4a"):
    """Write numbered, level-matched copies in play order, plus an M3U."""
    pl_dir = os.path.join(out_dir, "playlist")
    os.makedirs(pl_dir, exist_ok=True)
    enc, ext = _encode_args(fmt)

    common_lufs, gains = plan_gains(playlist)

    rows, m3u = [], ["#EXTM3U"]
    for t in playlist:
        title = t.get("title") or os.path.splitext(t["file"])[0]
        gain = gains.get(id(t), 0.0)
        name = f"{t['position']:02d}_{_safe(title)}{ext}"
        dst = os.path.join(pl_dir, name)

        cmd = [FFMPEG, "-y", "-v", "error", "-i", t["path"]]
        if abs(gain) > 0.05:
            cmd += ["-af", f"volume={gain}dB"]
        cmd += enc + [dst]
        p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        ok = p.returncode == 0

        rows.append({"position": t["position"], "title": title, "file": name,
                     "duration_s": t["duration_s"], "gain_db": gain,
                     "lufs_before": t["loudness"].get("lufs"), "ok": ok})
        m3u += [f"#EXTINF:{int(t['duration_s'])},{title}", name]

    with open(os.path.join(pl_dir, "playlist.m3u"), "w", encoding="utf-8") as f:
        f.write("\n".join(m3u) + "\n")

    return rows, pl_dir, common_lufs


def timestamp_lines(rows, gap_s: float = 0.0):
    """Cumulative chapter timestamps for a video description."""
    out, t = [], 0.0
    for r in rows:
        h, rem = divmod(int(t), 3600)
        m, s = divmod(rem, 60)
        stamp = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        out.append(f"{stamp} {r['title']}")
        t += r["duration_s"] + gap_s
    return out, t
