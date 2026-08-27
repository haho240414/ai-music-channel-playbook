#!/usr/bin/env python3
"""Track screening and playlist sequencing pipeline.

Usage
  # 1) Run collect.js in the generator's browser tab, save the JSON as tracks.json
  # 2) Download, analyze, screen, sequence, and export in one pass
  python3 run.py --urls tracks.json --out ./ep06 --episode "Episode Name" --export

  # Or analyze a folder of audio you already have
  python3 run.py --dir ./audio --out ./report --episode "Episode Name"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analyze import analyze_file          # noqa: E402
from export import export_playlist, timestamp_lines  # noqa: E402
from score import (WEIGHTS, discrimination, normalize_title,  # noqa: E402
                   pick_best_takes, score_cohort)
from sequence import build_playlist, limit_playlist  # noqa: E402

AUDIO_EXT = (".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg")
CLOSER_HINTS = ["walking home", "going home", "last", "packed", "closing", "end", "goodnight"]


def slug(s: str, i: int) -> str:
    s = re.sub(r"[^\w \-]", "", s, flags=re.UNICODE).strip().replace(" ", "_")[:48]
    return f"{i:02d}_{s or 'track'}"


def download(urls_json: str, audio_dir: str) -> list[dict]:
    """Download every audio URL from a collect.js result and return job metadata."""
    with open(urls_json, encoding="utf-8") as f:
        entries = json.load(f)

    os.makedirs(audio_dir, exist_ok=True)
    jobs = []
    for i, e in enumerate(entries, 1):
        title = e.get("title") or f"track{i}"
        bpm = e.get("target_bpm")
        for j, url in enumerate(e.get("urls") or []):
            name = slug(title, i) + (f"_take{j+1}" if len(e["urls"]) > 1 else "") + ".m4a"
            jobs.append({"url": url, "path": os.path.join(audio_dir, name),
                         "title": title, "target_bpm": bpm, "tags": e.get("tags"),
                         "downloaded": True})

    def fetch(job):
        path = job["path"]
        if os.path.exists(path) and os.path.getsize(path) > 10000:
            job["ok"] = True
            return job
        # Write to a temporary name and rename on success. A process killed mid-download
        # otherwise leaves a partial file that sails past any size check -- measured, a
        # 20%-truncated 3 MB track is 611 KB -- and is then treated as a cache hit
        # forever, failing to decode on every subsequent run.
        tmp = path + ".part"
        req = urllib.request.Request(job["url"], headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r, open(tmp, "wb") as out:
                shutil.copyfileobj(r, out)
            os.replace(tmp, path)
            job["ok"] = True
        except Exception as exc:  # noqa: BLE001
            # One dead link must not destroy the run. Generator URLs expire, and a
            # single 404 used to abort everything -- including the 6 of 7 files that
            # had already downloaded -- with a bare traceback and no report.
            job["ok"] = False
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return job

    with ThreadPoolExecutor(max_workers=4) as ex:
        done = list(ex.map(fetch, jobs))

    ok = [j for j in done if j.get("ok")]
    failed = [j for j in done if not j.get("ok")]
    print(f"  downloaded {len(ok)}/{len(done)} files -> {audio_dir}")
    if failed:
        print(f"  ! {len(failed)} download(s) failed; continuing without them:")
        for j in failed[:8]:
            print(f"      {os.path.basename(j['path'])}: {j.get('error')}")
        if len(failed) > 8:
            print(f"      ... and {len(failed) - 8} more")
    if not done:
        raise SystemExit("the input lists no audio URLs -- check the collect.js output")
    if not ok:
        raise SystemExit("every download failed -- check the URLs in the input")
    return ok, failed


def filename_to_title(name: str) -> str:
    """Recover a track title from a filename.

    Strips a leading index and EXPLICIT take markers only, reusing the same tested
    helper applied to generator-supplied titles. A bare trailing letter or digit is
    deliberately left alone: treating it as a take marker collapsed "Movement 1/2/3"
    into a single track and silently dropped two of them from the episode.
    """
    title = re.sub(r"^\d+[_-]", "", os.path.splitext(name)[0])
    return normalize_title(title.replace("_", " ").strip())


def collect_from_dir(audio_dir: str) -> list[dict]:
    jobs = []
    for name in sorted(os.listdir(audio_dir)):
        if name.lower().endswith(AUDIO_EXT):
            jobs.append({"path": os.path.join(audio_dir, name),
                         "title": filename_to_title(name), "target_bpm": None})
    return jobs


TIER_ICON = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}


def write_report(out_dir, episode, playlist, kept, dropped, all_results,
                 export_rows=None, common_lufs=None, unverified=None,
                 download_failures=None):
    lines = [f"# {episode} — screening and sequencing report", ""]
    lines += [f"- Files analyzed: **{len(all_results)}**",
              f"- After take selection: **{len(kept)}**",
              f"- Final playlist: **{len(playlist)}**", ""]

    if download_failures:
        lines += [f"> ⚠️ **{len(download_failures)} file(s) could not be downloaded** and "
                  f"are missing from this episode:", ""]
        for j in download_failures[:8]:
            lines.append(f"> - `{os.path.basename(j['path'])}` — {j.get('error')}")
        if len(download_failures) > 8:
            lines.append(f"> - … and {len(download_failures) - 8} more")
        lines.append("")

    if unverified:
        lines += [f"> ⚠️ **Instrumental check did not run.** No tag string was captured "
                  f"for any of the {unverified} files, so vocals could not be ruled out. "
                  f"Tag scraping depends on the generator's page format — see "
                  f"`collect.js`. Grades below reflect audio defects only.", ""]

    lines += ["## Playlist order", "",
              "| # | Track | Grade | Score | BPM | Key | LUFS | Transition |",
              "|---|---|---|---|---|---|---|---|"]
    for t in playlist:
        tr = t.get("transition")
        trs = "—" if not tr else (f"ΔBPM {tr['d_bpm']:+.0f} · key dist {tr['key_dist']:.0f}"
                                  f" · Δ{tr['d_energy_lu']:+.1f} LU")
        conf = t["key"].get("confidence", 1.0)
        kmark = "" if conf >= 0.5 else "?"  # marks a low-confidence key estimate
        lines.append(
            f"| {t['position']} | {t.get('title', t['file'])} | {TIER_ICON[t['tier']]} | "
            f"{t['score']:.0f} | {t['tempo']['bpm'] or '?'} | {t['key']['key'] or '?'}"
            f"{kmark} ({t['key']['camelot'] or '?'}) | {t['loudness'].get('lufs', '?')} | {trs} |"
        )

    if playlist:
        top = playlist[0]
        lines += ["", f"**Why this opens** — `{top.get('title', top['file'])}`: "
                      f"score {top['score']:.0f}, "
                      f"hook {top['subscores']['hook']:.0f}/{WEIGHTS['hook']} "
                      f"(full energy at {top['metrics']['time_to_full_s']}s, "
                      f"onset density {top['metrics']['onset_density_5s']}/s in the first 5s), "
                      f"motif repetition {top['subscores']['motif']:.0f}/"
                      f"{WEIGHTS['motif']}.", ""]

    lines += ["## Per-track detail", "",
              "| Track | Grade | Score | Hook | Motif | Pulse | Spectral | Dynamics | "
              "Stereo | Loudness | Defects |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    chosen = {id(t) for t in playlist}
    for r in sorted(all_results, key=lambda x: -x.get("score", 0)):
        s = r.get("subscores", {})
        real = [d for d in r["defects"] if d["severity"] != "info"]
        dfx = "; ".join(f"{d['type']}({d['severity']})" for d in real) or "none"
        mark = "" if id(r) in chosen else " *(not used)*"
        lines.append(
            f"| {r.get('title', r['file'])}{mark} | {TIER_ICON[r['tier']]} | {r.get('score', 0):.0f} | "
            f"{s.get('hook', 0):.0f} | {s.get('motif', 0):.0f} | {s.get('pulse', 0):.0f} | "
            f"{s.get('spectral', 0):.0f} | {s.get('dynamics', 0):.0f} | {s.get('stereo', 0):.0f} | "
            f"{s.get('loudness', 0):.0f} | {dfx} |"
        )

    if export_rows:
        stamps, total = timestamp_lines(export_rows)
        h, rem = divmod(int(total), 3600)
        m, s = divmod(rem, 60)
        dur = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
        lines += ["", "## Deliverables (playlist/)", "",
                  f"Numbered files level-matched to **{common_lufs} LUFS**, plus "
                  f"`playlist.m3u`. Total runtime **{dur}**.", "",
                  "> The target is not -14 LUFS because AI-generated tracks arrive already "
                  "peak-limited: raising them clamps against the true-peak ceiling by a "
                  "different amount per track, leaving the spread intact. Instead every "
                  "track is brought down to the highest level all of them can reach. "
                  "Playback loudness is normalized by the platform anyway.", "",
                  "| # | File | Original LUFS | Gain applied |", "|---|---|---|---|"]
        for r in export_rows:
            lines.append(f"| {r['position']} | `{r['file']}` | {r['lufs_before']} | "
                         f"{r['gain_db']:+.2f} dB |")
        lines += ["", "### Chapter timestamps", "", "```"] + stamps + ["```"]

    disc = discrimination(all_results)
    if disc:
        weak = [d for d in disc if d["verdict"] != "good"]
        lines += ["", "## Metric discrimination", "",
                  "How much each scoring metric actually separated *this* batch. A "
                  "near-constant metric adds a constant to every track and contributes "
                  "nothing to the ranking — if one shows up here, its weight is better "
                  "spent elsewhere on your material.", "",
                  "| Metric | Weight | Mean | Spread | |", "|---|---|---|---|---|"]
        for d in disc:
            icon = {"good": "🟢", "weak": "🟡", "near-constant": "🔴"}[d["verdict"]]
            lines.append(f"| {d['metric']} | {d['weight']} | {d['mean']} | "
                         f"{d['spread']:.0%} | {icon} {d['verdict']} |")
        if weak:
            lines += ["", f"{len(weak)} metric(s) below the useful threshold on this "
                          f"batch: {', '.join(d['metric'] for d in weak)}."]

    spots = [r for r in all_results if r.get("spot_check")]
    if spots:
        lines += ["", "## Spot-check points (not defects — may be intentional)", ""]
        for r in spots:
            for sc in r["spot_check"]:
                lines.append(f"- `{r.get('title', r['file'])}` — {sc}")

    if dropped:
        lines += ["", "## Dropped takes", ""]
        for d in dropped:
            lines.append(f"- `{d['file']}` — {d.get('dropped_reason', '')} "
                         f"(score {d.get('score', 0):.0f})")

    reds = [r for r in all_results if r["tier"] == "RED"]
    if reds:
        lines += ["", "## Regenerate (RED)", ""]
        for r in reds:
            for d in r["defects"]:
                if d["severity"] == "severe":
                    lines.append(f"- `{r.get('title', r['file'])}` — **{d['type']}**: {d['detail']}")

    lines += ["", "---", "",
              "### What this report judges, and what it does not", "",
              "**Judged** — defects that cannot be intentional (flattened-waveform "
              "clipping, mid-track silence, L/R phase inversion, DC offset, hard cuts, "
              "spectral seams), plus objective properties that correlate with usable "
              "tracks (hook immediacy, motif repetition, pulse clarity, spectral balance, "
              "dynamics, stereo width, loudness consistency).", "",
              "**Deliberately not asserted** — a weakening beat is indistinguishable from "
              "an intentional breakdown, so it is reported as a spot-check point and does "
              "not affect the grade.", "",
              "**Not judged** — whether a track is any good: subjective appeal, emotional "
              "fit, how well it suits the episode's subject. None of that is measurable. "
              "This ranking is a **shortlist for listening**, not a verdict.", ""]

    path = os.path.join(out_dir, "REPORT.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", help="JSON produced by collect.js")
    ap.add_argument("--dir", help="folder of audio files already downloaded")
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--episode", default="Untitled Episode")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap the final playlist length (0 = no cap)")
    ap.add_argument("--narrative", help='narrative order JSON {"Track Title": 0.0-1.0}, '
                                        "0 = opens the episode, 1 = closes it")
    ap.add_argument("--export", action="store_true",
                    help="also write level-matched numbered files, M3U, and timestamps")
    ap.add_argument("--export-format", choices=["m4a", "wav", "flac"], default="m4a")
    ap.add_argument("--require-instrumental", action="store_true",
                    help='warn when a track\'s tags omit "instrumental"')
    args = ap.parse_args()

    narrative = None
    if args.narrative:
        with open(args.narrative, encoding="utf-8") as f:
            narrative = json.load(f)

    os.makedirs(args.out, exist_ok=True)
    audio_dir = args.dir or os.path.join(args.out, "audio")

    download_failures = []
    if args.urls:
        print("[1/5] download")
        jobs, download_failures = download(args.urls, audio_dir)
    elif args.dir:
        jobs = collect_from_dir(args.dir)
        print(f"[1/5] {len(jobs)} existing files")
    else:
        ap.error("one of --urls or --dir is required")

    # Analysis is embarrassingly parallel and 86% of its time is spent waiting on
    # ffmpeg subprocesses, which release the GIL -- the EBU R128 pass alone is 73%.
    # Measured on 30 files: 24.1s serial -> 7.6s at 4 threads -> 5.8s at 8, with
    # byte-identical results. ex.map preserves input order, so progress lines and the
    # result list stay deterministic.
    workers = max(1, min(8, os.cpu_count() or 4))
    print(f"[2/5] analyze ({len(jobs)}, {workers} workers)")

    def _analyze(job):
        try:
            r = analyze_file(job["path"], target_bpm=job.get("target_bpm"))
            r["title"] = job.get("title")
            r["tags"] = job.get("tags")
            return job, r, None
        except Exception as exc:  # noqa: BLE001
            return job, None, exc

    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        analysed = list(ex.map(_analyze, jobs))

    for i, (j, r, err) in enumerate(analysed, 1):
        if err is not None:
            print(f"  {i}/{len(jobs)} {os.path.basename(j['path'])} -> failed: {err}")
            # Self-heal a corrupt download so the next run refetches it. Only ever
            # touch files this tool fetched -- never one the user pointed us at.
            if j.get("downloaded") and os.path.exists(j["path"]):
                os.remove(j["path"])
                print("      removed the unreadable download; it will be refetched")
            continue
        try:
            # Instrumental-channel check: generators sometimes ignore "no vocals", so
            # warn when the returned tag string does not say instrumental.
            if args.require_instrumental:
                tags = str(r["tags"] or "").strip()
                if tags and "instrumental" not in tags.lower():
                    r["defects"].append({
                        "type": "possible_vocals", "severity": "warn",
                        "detail": f"tags omit 'instrumental': {tags[:80]}"})
                    if r["tier"] == "GREEN":
                        r["tier"] = "YELLOW"
            results.append(r)
            print(f"  {i}/{len(jobs)} {r['file']} -> {r['tier']}")
        except Exception as e:  # noqa: BLE001
            print(f"  {i}/{len(jobs)} {os.path.basename(j['path'])} -> failed: {e}")

    # Tags missing on SOME tracks is a per-track problem, already flagged above.
    # Tags missing on ALL of them is a setup problem -- tag scraping is page-format
    # dependent and fails silently -- so say it once instead of downgrading every
    # track's grade and rendering the grade column meaningless.
    unverified = None
    if args.require_instrumental and results:
        untagged = [r for r in results if not str(r.get("tags") or "").strip()]
        if len(untagged) == len(results):
            unverified = len(untagged)
            print(f"  ! no tag strings captured: vocals could not be ruled out on any "
                  f"of the {unverified} files")
        else:
            for r in untagged:
                r["defects"].append({
                    "type": "unverified_instrumental", "severity": "warn",
                    "detail": "no tag string captured, so vocals could not be ruled out"})
                if r["tier"] == "GREEN":
                    r["tier"] = "YELLOW"

    print("[3/5] cohort scoring")
    score_cohort(results)

    print("[4/5] take selection")
    kept, dropped = pick_best_takes(results)

    print("[5/5] sequencing")
    playlist = build_playlist(kept, closer_hint=CLOSER_HINTS, narrative=narrative)
    if args.limit:
        playlist = limit_playlist(playlist, args.limit,
                                  closer_hint=CLOSER_HINTS, narrative=narrative)

    export_rows = None
    export_rows_target = None
    if args.export:
        print("[6/6] loudness normalization and export")
        export_rows, pl_dir, common_lufs = export_playlist(
            playlist, args.out, fmt=args.export_format)
        export_rows_target = common_lufs
        failed = [r for r in export_rows if not r["ok"]]
        print(f"  {len(export_rows) - len(failed)}/{len(export_rows)} tracks "
              f"-> {common_lufs} LUFS, {pl_dir}")
        if failed:
            print(f"  failed: {[r['file'] for r in failed]}")

    with open(os.path.join(args.out, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump({"episode": args.episode, "results": results,
                   "playlist": [t.get("title") or t["file"] for t in playlist]},
                  f, ensure_ascii=False, indent=2)

    path = write_report(args.out, args.episode, playlist, kept, dropped, results,
                        export_rows, export_rows_target, unverified,
                        download_failures)
    print(f"\ndone -> {path}")


if __name__ == "__main__":
    main()
