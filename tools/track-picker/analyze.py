"""Per-track audio analysis: defect detection (a reject filter) and quality metrics.

Everything here is signal processing. Nothing here judges whether a track is *good* —
that is not measurable. What it measures are objective properties that correlate with
usable tracks: hook immediacy, motif repetition, spectral balance, dynamics, stereo
width, and loudness.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

import numpy as np


def _find_ffmpeg() -> str:
    """Locate ffmpeg. Set FFMPEG_BIN to override."""
    env = os.environ.get("FFMPEG_BIN")
    if env and os.path.exists(env):
        return env
    from shutil import which
    found = which("ffmpeg")
    if found:
        return found
    for c in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.exists(c):
            return c
    return "ffmpeg"


FFMPEG = _find_ffmpeg()
SR = 22050


class FFmpegMissing(RuntimeError):
    """The ffmpeg binary itself is unavailable.

    Kept distinct from a decode failure: "this file is broken" and "I have no decoder"
    look identical at the call site, and treating the second as the first once deleted
    every downloaded file in a batch.
    """


def ffmpeg_available() -> bool:
    try:
        subprocess.run([FFMPEG, "-version"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


# ---------------------------------------------------------------- decoding


def decode(path: str, sr: int = SR):
    """m4a/mp3/wav -> float64 (L, R, mono)."""
    cmd = [FFMPEG, "-v", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", str(sr), "-"]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise FFmpegMissing(f"cannot run ffmpeg ({FFMPEG}): {exc}") from exc
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed: {p.stderr.decode(errors='ignore')[:300]}")
    x = np.frombuffer(p.stdout, dtype=np.float32).reshape(-1, 2).astype(np.float64)
    L, R = x[:, 0], x[:, 1]
    return L, R, (L + R) * 0.5


def loudness(path: str) -> dict:
    """EBU R128: integrated LUFS, loudness range (LRA), true peak (dBTP)."""
    cmd = [FFMPEG, "-hide_banner", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"]
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    err = p.stderr.decode(errors="ignore")
    tail = err[err.rfind("Summary:"):] if "Summary:" in err else err

    def grab(label):
        m = re.search(label + r":\s*(-?\d+\.?\d*)", tail)
        return float(m.group(1)) if m else None

    return {"lufs": grab("I"), "lra": grab("LRA"), "true_peak": grab("Peak")}


# ---------------------------------------------------------------- basic signal


def stft_mag(y: np.ndarray, n_fft: int = 2048, hop: int = 1024) -> np.ndarray:
    if len(y) < n_fft:
        return np.zeros((0, n_fft // 2 + 1))
    frames = np.lib.stride_tricks.sliding_window_view(y, n_fft)[::hop]
    return np.abs(np.fft.rfft(frames * np.hanning(n_fft), axis=1))


def rms_envelope(y: np.ndarray, sr: int, win_s: float = 0.1) -> np.ndarray:
    win = max(1, int(win_s * sr))
    n = len(y) // win
    if n == 0:
        return np.array([0.0])
    trimmed = y[: n * win].reshape(n, win)
    return np.sqrt(np.mean(trimmed ** 2, axis=1) + 1e-12)


def active_region(env: np.ndarray, win_s: float = 0.1):
    """Index range of the actual music, excluding lead-in and fade-out.

    Finding each track's real start and end beats trimming a fixed number of seconds:
    fade lengths vary per track, and a fixed guard makes every fade-out look like a
    dropout.
    """
    if env.size == 0:
        return 0, 0
    med = np.median(env)
    thr = med * 0.10  # -20 dB relative to median
    active = np.where(env > thr)[0]
    if active.size == 0:
        return 0, len(env)
    return int(active[0]), int(active[-1]) + 1


def onset_envelope(y: np.ndarray, sr: int, n_fft: int = 1024, hop: int = 256,
                   n_bands: int = 40):
    """High-resolution onset strength curve (per-band positive spectral flux).

    Tempo analysis needs fine time resolution. At hop 1024 adjacent autocorrelation lags
    map to BPM values 7-8 apart, which manufactures variance out of nothing. Computed in
    chunks to bound memory.
    """
    if len(y) < n_fft * 4:
        return np.zeros(0), sr / hop

    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    edges = np.logspace(np.log10(40.0), np.log10(sr / 2 * 0.95), n_bands + 1)
    band_idx = [np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0]
                for i in range(n_bands)]
    window = np.hanning(n_fft)

    total = 1 + (len(y) - n_fft) // hop
    out, prev = [], None
    for s in range(0, total, 2048):
        e = min(total, s + 2048)
        seg = y[s * hop: (e - 1) * hop + n_fft]
        if len(seg) < n_fft:
            break
        fr = np.lib.stride_tricks.sliding_window_view(seg, n_fft)[::hop]
        mag = np.abs(np.fft.rfft(fr * window, axis=1))
        bands = np.log1p(np.stack(
            [mag[:, bi].sum(axis=1) if bi.size else np.zeros(mag.shape[0])
             for bi in band_idx], axis=1))
        full = bands if prev is None else np.vstack([prev, bands])
        out.append(np.sum(np.maximum(np.diff(full, axis=0), 0.0), axis=1))
        prev = bands[-1:]

    env = np.concatenate(out) if out else np.zeros(0)
    return env, sr / hop


# ---------------------------------------------------------------- tempo / rhythm

# Autocorrelation cannot distinguish a beat period from its multiples. Folding must
# include 2/3 and 3/2 (triplet-vs-duple readings of the same groove), not just x2 and
# x1/2 -- handling only octaves leaves every track flagged for phantom "tempo drift".
_METRICAL = (1 / 3, 1 / 2, 2 / 3, 3 / 4, 1.0, 4 / 3, 3 / 2, 2.0, 3.0)

# Beat-grid reporting thresholds, all calibrated against a real 30-file batch.
UNRELIABLE_PULSE = 0.10     # below this the tempo estimate, not the playing, is wrong
WEAK_PULSE_CEILING = 0.20   # absolute ceiling for calling a window weak
MIN_WEAK_WINDOWS = 3        # fewer than this is noise, not a passage


def _autocorr(env: np.ndarray) -> np.ndarray:
    e = env - env.mean()
    n = len(e)
    nfft = 1 << (2 * n - 1).bit_length()
    F = np.fft.rfft(e, nfft)
    return np.fft.irfft(F * np.conj(F), nfft)[:n]


def _parabolic(ac: np.ndarray, k: int) -> float:
    """Interpolate the autocorrelation peak to sub-frame precision for BPM resolution."""
    if k <= 0 or k >= len(ac) - 1:
        return float(k)
    a, b, c = ac[k - 1], ac[k], ac[k + 1]
    d = a - 2 * b + c
    return float(k) if d == 0 else float(k + 0.5 * (a - c) / d)


def metrical_fold(bpm, ref):
    if bpm is None or ref is None:
        return bpm
    return min([bpm * f for f in _METRICAL], key=lambda c: abs(c - ref))


def pulse_strength(env: np.ndarray, period: float) -> float:
    """Normalized autocorrelation of the onset envelope at one beat period.

    How well a beat grid at this period actually explains the signal. Near zero or
    negative means it does not.
    """
    if env.size < 8 or period is None:
        return -1.0
    P = int(round(period))
    if P < 2 or P >= len(env):
        return -1.0
    e = env - env.mean()
    den = float(np.sum(e * e)) + 1e-12
    return float(np.sum(e[:-P] * e[P:])) / den * len(e) / max(1, len(e) - P)


def fold_to_range(bpm, env=None, frame_rate=None,
                  lo=55.0, hi=190.0, prefer=105.0, sigma=0.75):
    """When no target BPM is known, pick the metrical level the signal supports.

    Autocorrelation gives the same answer for 60 and 120 BPM, so something has to break
    the tie. Choosing purely by "closest to a preferred tempo" picks the wrong multiple
    often enough to wreck the downstream beat-grid analysis -- measured on a real batch,
    5 of 30 tracks ended up with *negative* pulse clarity, meaning the grid anti-aligned
    with the music.

    So score each candidate by how well a grid at that period explains the onset envelope,
    damped by a log-normal tempo prior (a plain maximum would always favour the fastest
    multiple, since a signal periodic at P also correlates at P/2).
    """
    if bpm is None:
        return None
    cands = [c for c in (bpm * f for f in _METRICAL) if lo <= c <= hi] or [bpm]

    if env is None or frame_rate is None:
        return min(cands, key=lambda c: abs(c - prefer))

    def score(c):
        prior = float(np.exp(-0.5 * (np.log2(c / prefer) / sigma) ** 2))
        return pulse_strength(env, 60.0 * frame_rate / c) * prior

    return max(cands, key=score)


def estimate_tempo(env: np.ndarray, frame_rate: float, target_bpm=None,
                   lo=55.0, hi=190.0):
    """One precise representative BPM for the whole track."""
    if env.size < 64:
        return {"bpm": None, "period_frames": None}
    ac = _autocorr(env)
    min_lag = max(2, int(frame_rate * 60.0 / hi))
    max_lag = min(len(ac) - 2, int(frame_rate * 60.0 / lo))
    if min_lag >= max_lag:
        return {"bpm": None, "period_frames": None}
    k = int(np.argmax(ac[min_lag:max_lag])) + min_lag
    lag = _parabolic(ac, k)
    bpm = 60.0 * frame_rate / lag
    folded = (metrical_fold(bpm, target_bpm) if target_bpm
              else fold_to_range(bpm, env=env, frame_rate=frame_rate))
    if folded:
        bpm = folded
        lag = 60.0 * frame_rate / bpm
    return {"bpm": round(bpm, 1), "period_frames": lag}


def rhythm_stability(env: np.ndarray, frame_rate: float, period: float,
                     rms_env: np.ndarray | None = None, rms_rate: float = 10.0,
                     win_s: float = 8.0, hop_s: float = 4.0):
    """Track beat-grid coherence over time.

    For each window, measure how well the signal overlaps itself one beat later
    (normalized autocorrelation at the beat period). Where that collapses, the pulse is
    genuinely gone.

    Windows where there is no beat *by design* -- intro build-ups, outro fades -- are
    skipped: anything below 60% of the track's median energy is not judged. Without this
    guard every track flags at its own intro and outro.
    """
    if env.size < 64 or not period or period < 2:
        return {"clarity_median": None, "weak_windows": []}
    P = int(round(period))
    W, H = int(win_s * frame_rate), max(1, int(hop_s * frame_rate))

    med_rms = None
    if rms_env is not None and rms_env.size:
        pos = rms_env[rms_env > 0]
        med_rms = float(np.median(pos)) if pos.size else None

    vals = []
    for s in range(0, max(1, len(env) - W), H):
        seg = env[s:s + W]
        if len(seg) < P * 3:
            continue
        t0 = s / frame_rate
        if med_rms is not None:
            i0, i1 = int(t0 * rms_rate), int((t0 + win_s) * rms_rate)
            win_rms = rms_env[i0:i1]
            if win_rms.size == 0 or float(np.mean(win_rms)) < 0.60 * med_rms:
                continue  # no beat expected here; do not judge
        e = seg - seg.mean()
        denom = float(np.sum(e * e)) + 1e-12
        num = float(np.sum(e[:-P] * e[P:]))
        vals.append((round(t0, 1), num / denom * len(e) / max(1, len(e) - P)))

    if len(vals) < 3:
        return {"clarity_median": None, "weak_windows": []}
    clar = np.array([v for _, v in vals])
    med = float(np.median(clar))

    # If the grid barely explains the music anywhere, the tempo estimate is wrong rather
    # than the performance being loose. Listing 33 "weak" windows out of 36 is noise, so
    # report the low clarity and emit no timestamps.
    if med < UNRELIABLE_PULSE:
        return {"clarity_median": round(med, 3), "weak_windows": [],
                "windows_judged": len(vals), "grid_unreliable": True}

    # Weak both relative to this track AND in absolute terms. A purely relative
    # threshold flags still-clear windows on a crisp track while letting a mushy one
    # off, which is backwards.
    thr = max(0.04, min(med * 0.40, WEAK_PULSE_CEILING))
    weak = [(t, round(c, 3)) for (t, c) in vals if c < thr]

    # One or two weak windows out of forty is noise, not a passage worth checking.
    if len(weak) < MIN_WEAK_WINDOWS:
        weak = []

    return {"clarity_median": round(med, 3), "weak_windows": weak,
            "windows_judged": len(vals)}


# ---------------------------------------------------------------- key

_PC = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_KS_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
_CAMELOT_MAJ = {0: 8, 1: 3, 2: 10, 3: 5, 4: 12, 5: 7, 6: 2, 7: 9, 8: 4, 9: 11, 10: 6, 11: 1}
_CAMELOT_MIN = {9: 8, 10: 3, 11: 10, 0: 5, 1: 12, 2: 7, 3: 2, 4: 9, 5: 4, 6: 11, 7: 6, 8: 1}


def estimate_key(mag: np.ndarray, sr: int, n_fft: int):
    """Chroma -> Krumhansl-Schmuckler correlation -> key plus Camelot code."""
    if mag.shape[0] == 0:
        return {"key": None, "camelot": None, "confidence": 0.0}
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    band = (freqs > 55) & (freqs < 2200)
    pcs = np.full(freqs.shape, -1, dtype=int)
    pcs[band] = np.round(12 * np.log2(freqs[band] / 440.0)).astype(int) % 12

    spec = np.median(mag, axis=0)
    chroma = np.zeros(12)
    for pc in range(12):
        chroma[pc] = spec[pcs == pc].sum()
    if chroma.sum() <= 0:
        return {"key": None, "camelot": None, "confidence": 0.0}
    chroma = chroma / chroma.sum()

    scored = []
    for root in range(12):
        for mode, prof in (("maj", _KS_MAJ), ("min", _KS_MIN)):
            r = float(np.corrcoef(chroma, np.roll(prof, root))[0, 1])
            scored.append((r, root, mode))
    scored.sort(reverse=True)
    best_r, root, mode = scored[0]

    # Margin between the best and second-best key = how much to trust this estimate.
    # Measured across one batch it ranged from 0.03 (a coin flip) to 0.29 (certain).
    # The sequencer scales the key term by this so it does not optimize against noise.
    margin = best_r - scored[1][0]
    conf = float(np.clip(margin / 0.20, 0.0, 1.0))

    num = (_CAMELOT_MAJ if mode == "maj" else _CAMELOT_MIN)[root]
    return {"key": f"{_PC[root]}{'m' if mode == 'min' else ''}",
            "camelot": f"{num}{'B' if mode == 'maj' else 'A'}",
            "confidence": round(conf, 2), "corr": round(best_r, 3)}


# ---------------------------------------------------------------- defect detection


def detect_defects(L, R, mono, sr, env, a0, a1, mag, frame_rate, tempo, rhythm, target_bpm):
    defects = []

    # 1) Real clipping: only runs of consecutive samples at ceiling (a flattened
    #    waveform). Isolated peaks are normal -- counting those reported 0.113%
    #    "clipping" on a clean track.
    at_ceiling = np.abs(mono) >= 0.995
    if at_ceiling.any():
        edges = np.diff(at_ceiling.astype(np.int8))
        starts = np.where(edges == 1)[0] + 1
        ends = np.where(edges == -1)[0] + 1
        if at_ceiling[0]:
            starts = np.r_[0, starts]
        if at_ceiling[-1]:
            ends = np.r_[ends, len(at_ceiling)]
        n = min(len(starts), len(ends))
        runs = (ends[:n] - starts[:n])
        hard = int(np.sum(runs >= 4))  # 4+ consecutive samples = flattened
        if hard >= 20:
            defects.append(("clipping", "severe",
                            f"{hard} flattened waveform runs (digital distortion)"))
        elif hard >= 5:
            defects.append(("clipping", "warn", f"{hard} flattened waveform runs (mild)"))

    # 2) Interior dropout: only inside the real music, and only *contiguous* silence.
    #    Brief gaps between notes in a sparse intro are normal, so scattered dips are
    #    ignored.
    interior = env[a0:a1]
    if interior.size > 30:
        med_db = 20 * np.log10(np.median(interior) + 1e-9)
        env_db = 20 * np.log10(interior + 1e-9)
        margin = int(2.0 / 0.1)
        core = env_db[margin:-margin]
        low = core < med_db - 28
        if low.any():
            runs, start = [], None
            for i, v in enumerate(low):
                if v and start is None:
                    start = i
                elif not v and start is not None:
                    runs.append((start, i))
                    start = None
            if start is not None:
                runs.append((start, len(low)))
            long_runs = [r for r in runs if (r[1] - r[0]) >= 4]  # 0.4s+ contiguous
            if long_runs:
                ts = [round((a0 + margin + r[0]) * 0.1, 1) for r in long_runs[:6]]
                defects.append(("dropout", "severe", f"silence/gap mid-track at t={ts}s"))

    # 3) Hard cut: the final moment is still at full energy, so the track was cut off.
    if a1 - a0 > 20:
        tail = env[max(a0, a1 - 5):a1]
        if tail.size and np.median(tail) > np.median(env[a0:a1]) * 0.75:
            defects.append(("hard_cut", "warn", "track ends abruptly with no fade"))

    # 4) Spectral seam: an abrupt timbral jump between adjacent frames.
    if mag.shape[0] > 20:
        norm = mag / (mag.sum(axis=1, keepdims=True) + 1e-12)
        flux = np.sum(np.abs(np.diff(norm, axis=0)), axis=1)
        lo = int(mag.shape[0] * 0.05)
        core = flux[lo:-lo] if mag.shape[0] > 2 * lo else flux
        med, mad = np.median(core), np.median(np.abs(core - np.median(core))) + 1e-9
        spikes = np.where(core > med + 14 * mad)[0]
        if spikes.size:
            ts = sorted({round((lo + s) / frame_rate, 1) for s in spikes})[:6]
            sev = "severe" if spikes.size >= 4 else "warn"
            defects.append(("seam", sev, f"abrupt timbre change at t={ts}s"))

    # 5) Weakening beat -> reported as a spot-check hint only, never as a defect.
    #    An intentional breakdown (drums dropping out for eight bars) and a real glitch
    #    are indistinguishable from the signal alone. Asserting either way produces
    #    false positives, so this does not affect the grade.
    weak = rhythm.get("weak_windows") or []
    if weak:
        ts = [t for t, _ in weak[:6]]
        defects.append(("rhythm_break", "info",
                        f"beat weakens at t={ts}s - may be an intentional breakdown"))

    # 6) Target BPM mismatch (after metrical folding, so this means the prompt was
    #    not followed).
    if target_bpm and tempo["bpm"]:
        off = abs(tempo["bpm"] - target_bpm)
        if off > 14:
            defects.append(("tempo_mismatch", "warn",
                            f"measured {tempo['bpm']} bpm vs target {target_bpm} bpm"))

    # 7) DC offset
    if abs(float(np.mean(mono))) > 0.01:
        defects.append(("dc_offset", "warn", f"DC offset {float(np.mean(mono)):.3f}"))

    # 8) Phase inversion: the track partially disappears when summed to mono.
    if np.std(L) > 1e-6 and np.std(R) > 1e-6:
        corr = float(np.corrcoef(L, R)[0, 1])
        if corr < -0.2:
            defects.append(("phase", "severe", f"L/R phase inversion (corr={corr:.2f})"))

    return defects


# ---------------------------------------------------------------- quality metrics


def quality_metrics(L, R, mono, sr, env, a0, a1, mag, onset, onset_rate,
                    mag_rate, rhythm=None):
    """Feature extraction.

    Two different frame rates are in play and they are not interchangeable: `onset` is
    computed at a fine hop for tempo work, while `mag` uses a coarser STFT hop. Applying
    the onset rate to the magnitude array silently scans the wrong lag window.
    """
    m = {}

    # Beat clarity as a *quality* metric rather than a defect: it cannot be separated
    # from an intentional breakdown, but a channel promising clear rhythms can score on
    # it.
    m["pulse_clarity"] = (rhythm or {}).get("clarity_median") or 0.0

    # Hook immediacy: time to reach full energy.
    #
    # Guard against a silent or near-silent file: it trivially "reaches" 80% of its own
    # (zero) median at t=0, which otherwise scores as a perfect instant hook.
    med = np.median(env[a0:a1]) if a1 > a0 else np.median(env)
    if not np.isfinite(med) or med < 1e-4:  # ~-80 dBFS: no signal, metric undefined
        m["time_to_full_s"] = 99.0
    else:
        idx = np.where(env >= med * 0.8)[0]
        m["time_to_full_s"] = round(float(idx[0] * 0.1), 2) if idx.size else 99.0

    # Onset density in the first 5s: is there actually a rhythm or melody, or is this a
    # pad drone?
    n5 = int(5.0 * onset_rate)
    if onset.size > n5 > 0:
        head, whole = onset[:n5], onset
        thr = np.median(whole) + np.std(whole) * 0.5
        m["onset_density_5s"] = round(float(np.sum(head > thr) / 5.0), 2)
    else:
        m["onset_density_5s"] = 0.0

    # Motif repetition: how strongly the feature sequence recurs at phrase-length lags
    # (5-30s) -- a proxy for a memorable hook coming back.
    if mag.shape[0] > 40:
        bands = np.array_split(mag, 24, axis=1)
        feat = np.stack([np.log1p(b.sum(axis=1)) for b in bands], axis=1)
        feat = feat - feat.mean(axis=0, keepdims=True)
        nrm = np.linalg.norm(feat, axis=1, keepdims=True) + 1e-9
        feat = feat / nrm
        # Lag bounds must use the MAGNITUDE frame rate, since feat comes from `mag`.
        lo_lag = int(5 * mag_rate)
        hi_lag = min(int(30 * mag_rate), feat.shape[0] - 10)
        step = max(1, int(0.5 * mag_rate))
        best = 0.0
        for lag in range(lo_lag, hi_lag, step):
            if lag <= 0 or lag >= feat.shape[0]:
                continue  # nothing to correlate against
            sim = float(np.mean(np.sum(feat[:-lag] * feat[lag:], axis=1)))
            if np.isfinite(sim):
                best = max(best, sim)
        m["motif_repetition"] = round(best, 3)
    else:
        m["motif_repetition"] = 0.0

    # Stereo width (mid/side energy ratio)
    mid, side = (L + R) / 2, (L - R) / 2
    me, se = float(np.mean(mid ** 2)), float(np.mean(side ** 2))
    m["stereo_width"] = round(float(np.sqrt(se / (me + 1e-12))), 3)

    # Crest factor (peak / RMS) = dynamic headroom
    peak, rms = float(np.max(np.abs(mono)) + 1e-12), float(np.sqrt(np.mean(mono ** 2)) + 1e-12)
    m["crest_db"] = round(20 * np.log10(peak / rms), 2)

    # Six-band relative spectral profile, for cohort comparison
    freqs = np.fft.rfftfreq((mag.shape[1] - 1) * 2, 1.0 / sr)
    edges = [20, 80, 250, 800, 2500, 6000, 11000]
    spec = np.mean(mag, axis=0)
    prof = []
    for i in range(len(edges) - 1):
        sel = (freqs >= edges[i]) & (freqs < edges[i + 1])
        prof.append(float(spec[sel].sum()))
    total = sum(prof) + 1e-12
    m["spectral_profile"] = [round(p / total, 4) for p in prof]

    return m


# ---------------------------------------------------------------- single track


def analyze_file(path: str, target_bpm=None) -> dict:
    L, R, mono = decode(path)
    sr = SR
    n_fft, hop = 2048, 1024
    frame_rate = sr / hop

    env = rms_envelope(mono, sr, 0.1)
    a0, a1 = active_region(env)
    mag = stft_mag(mono, n_fft, hop)

    onset, onset_fr = onset_envelope(mono, sr)
    tempo = estimate_tempo(onset, onset_fr, target_bpm)
    rhythm = rhythm_stability(onset, onset_fr, tempo.get("period_frames"),
                              rms_env=env, rms_rate=10.0)

    res = {
        "file": os.path.basename(path),
        "path": path,
        # Full precision, not rounded. Chapter timestamps accumulate these, so 0.1 s
        # rounding compounds: ~1.5 s of drift by track 30, enough to misplace a chapter
        # at the one-second granularity timestamps are displayed in.
        "duration_s": len(mono) / sr,
        "target_bpm": target_bpm,
        "tempo": tempo,
        "rhythm": rhythm,
        "key": estimate_key(mag, sr, n_fft),
        "loudness": loudness(path),
        "metrics": quality_metrics(L, R, mono, sr, env, a0, a1, mag, onset,
                                   onset_rate=onset_fr, mag_rate=frame_rate,
                                   rhythm=rhythm),
    }
    res["defects"] = [
        {"type": t, "severity": s, "detail": d}
        for t, s, d in detect_defects(L, R, mono, sr, env, a0, a1, mag,
                                      frame_rate, tempo, rhythm, target_bpm)
    ]
    # RED is reserved for defects that cannot be intentional (clipping, mid-track
    # silence, phase inversion). "info" entries are spot-check hints and do not affect
    # the grade.
    sev = sum(1 for d in res["defects"] if d["severity"] == "severe")
    warn = sum(1 for d in res["defects"] if d["severity"] == "warn")
    res["tier"] = "RED" if sev else ("YELLOW" if warn else "GREEN")
    res["spot_check"] = [d["detail"] for d in res["defects"] if d["severity"] == "info"]
    return res


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(json.dumps(analyze_file(p), ensure_ascii=False))
