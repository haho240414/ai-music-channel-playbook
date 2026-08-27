# Quality screening

An episode is 15 prompts × 2 takes = 30 files. Listening to all of them is the bottleneck
that makes the whole pipeline not worth running.

This is what can be automated, what cannot, and why drawing that line carefully matters
more than any individual check.

## What a machine can and cannot judge

**Can**: whether a track is technically broken. Digital clipping, a silent gap in the
middle, phase-inverted channels, a hard cut. These are unambiguous — no producer chose them.

**Cannot**: whether a track is any good. Whether the melody grabs you, whether it fits the
episode's feeling, whether the harmony is tasteful. There is no signal-processing proxy for
taste.

The temptation is to blur these together and ship a tool that ranks tracks by "quality".
Don't. A tool that flags a real dropout at 18.8s earns trust. A tool that says track 7 is
better than track 4 loses it the first time you disagree.

The split used here:

- **Defect detection** decides RED — reject and regenerate
- **Objective scoring** produces a *ranking*, explicitly labeled as a shortlist for human
  listening, not a verdict

## Defect detection

Only things that cannot be intentional.

### True clipping

Not "a sample hit full scale" — a single peak at ceiling is normal. Real clipping flattens
the waveform. Count **runs of 4+ consecutive samples** at |x| ≥ 0.995.

Counting isolated peaks instead produced a 0.113% "clipping" reading on a perfectly clean
track. Run-length detection cleared it correctly.

### Interior dropout

A silent gap where music should be. Two guards against false positives:

1. **Trim the real fade in/out first.** Find where the music actually starts and ends
   rather than skipping a fixed number of seconds — fade lengths vary per track.
2. **Require contiguity.** Only flag runs of 0.4s+ below threshold. Scattered dips are
   just sparse arrangement between notes.

Without guard 1, every track flags at its own fade-out. Without guard 2, every sparse
intro flags.

### Phase inversion

Correlation between L and R below −0.2. The track will partially disappear on mono playback.

### DC offset and hard cuts

Mean sample value meaningfully away from zero; or a track whose final moment is still at
full energy with no fade, meaning it was cut off mid-phrase.

## Tempo: the trap

The obvious approach — estimate BPM in chunks, flag tracks whose BPM varies — produces
almost entirely false positives. Two separate reasons:

### Metrical ambiguity

Autocorrelation cannot distinguish a beat period from its multiples. A 107.7 BPM track
reads as 71.8 BPM in one chunk. That is 107.7 × 2/3 — a triplet-vs-duple reading of the
same groove, not a tempo change.

Folding candidates must include **2/3 and 3/2**, not just ×2 and ×½. Handling only octaves
left every track in a batch flagged for "tempo drift".

### Resolution

At a coarse analysis hop, adjacent lag values map to BPM values 7–8 apart, manufacturing
variance out of nothing. Use a fine hop for the onset envelope and interpolate the
autocorrelation peak to sub-frame precision.

With both fixed, BPM estimates landed within ~1–2 BPM of the prompted values across a batch
— without being told the target.

### Choosing the metrical level when no target BPM is known

Folding into a "preferred tempo range" and picking whatever lands closest to it is the
obvious approach and it is wrong often enough to matter. On a real 30-file batch it put
**6 tracks on a grid that anti-aligned with the music** — negative pulse clarity — which
makes every downstream rhythm measurement meaningless.

Score each metrical candidate by how well a beat grid at that period actually explains
the onset envelope, damped by a log-normal tempo prior. The prior is still needed: a
signal periodic at P also correlates at P/2, so a plain maximum always picks the fastest
multiple.

```
score(candidate) = pulse_strength(period) × exp(−½ (log₂(candidate / 105) / 0.75)²)
```

Measured on that batch, blind estimates went from consistently ~4/3 too fast to matching
the prompted BPM within 1–2 on 9 of 10 tracks:

| Prompted | Preference-only | Grid-scored |
|---|---|---|
| 86 | 101–114 | **84.9 / 86.0** |
| 82 | 109.8 | **82.4** |
| 80 | 106.7 | **80.0** |
| 72 | 110.1 | **73.4** |
| 88 | 118.7 | **89.0** |

Tracks below the reliability floor: **6 of 30 → 0 of 30**.

### What to measure instead

Not "did the BPM change" but **did the beat fall apart**. For each window, compute the
normalized autocorrelation at the global beat period — how well the signal overlaps itself
one beat later. Where that collapses, the pulse is genuinely gone.

Then the critical guard: **skip windows where there's no beat by design.** Intro build-ups
and outro fades legitimately have no drums. Only evaluate windows whose energy is at least
~60% of the track median. Without this, every track flags at its intro and outro.

Three more rules keep the output actionable rather than noisy:

- **If the track's median clarity is very low, say so and emit no timestamps.** That means
  the tempo estimate is wrong, not that the playing is loose — listing 33 weak windows out
  of 36 tells the reader nothing.
- **Require a weak window to be weak in absolute terms too**, not only relative to its own
  track. A purely relative threshold flags still-clear passages on a crisp track while
  letting a mushy one off, which is backwards.
- **Require a minimum count.** One or two weak windows out of forty is noise.

Tightening these cut spot-check reports from 36% of tracks to 23% — the difference between
a hint someone reads and one they learn to skip.

### And then don't call it a defect

Even after all that, a collapsed beat can be an intentional breakdown — drums dropping out
for eight bars is a normal musical device. Signal analysis cannot distinguish that from a
glitch.

So beat collapse is reported as a **timestamp to spot-check**, not a defect, and it does not
affect the grade. Meanwhile the *median* pulse clarity across the track becomes a positive
scoring metric — a channel promising "clear rhythms" can score tracks on exactly that.

This is the general shape of the lesson: when a measurement is ambiguous between "broken"
and "deliberate", it belongs in scoring or in a hint, never in a reject decision.

## Objective scoring

For ranking only. Seven metrics, weighted to 100:

| Metric | Weight | What it measures | Spread measured |
|---|---|---|---|
| Hook immediacy | 24 | Time to reach full energy + onset density in the first 5s | 93% |
| Motif repetition | 20 | Self-similarity strength at phrase-length lags (5–30s) | 80% |
| Spectral balance | 15 | Distance from the batch's median spectral profile | 93% |
| Loudness consistency | 14 | LUFS agreement with the batch, true-peak headroom | 66% |
| Pulse clarity | 13 | Median beat-grid coherence | 80% |
| Dynamics | 11 | Crest factor and EBU R128 loudness range | 38% |
| Stereo width | 3 | Mid/side energy ratio — a guard, not a ranking axis | 12% |

Two design choices worth copying:

**Score relative to the batch, not to invented targets.** There is no correct spectral
balance for a genre. But a track that is a clear outlier *among its own episode* is worth
looking at. Comparing against the cohort median avoids fabricating numbers.

**But check the batch has spread before ranking on it.** A percentile ramp stretches
p10–p90 across the full score range *whatever that interval is*. Give it a degenerate
batch — takes of one track, a handful of near-identical files — and it turns a 2%
measurement difference into a full-marks difference.

Measured: six encodings of one song (WAV, FLAC, MP3 at 320/128/64k, AAC 96k) whose raw
motif and pulse values agreed to within 5% scored **78.6 to 94.1**. Confident-looking
numbers, pure noise.

When a cohort metric's raw p10–p90 spread falls below ~20%, flatten it to a neutral value
and say so, rather than ranking on noise. On a real 30-track batch nothing flattens
(motif 50%, pulse 68% raw spread) and no score moves; on the degenerate batch the spurious
15.5-point spread collapses to 0.7.

The same trap catches the diagnostic: **subscore spread cannot reveal this**, because the
ramp guarantees a wide subscore spread regardless. Report the *raw* spread for
percentile-ramped metrics.

**Floor the relative metrics.** Mapping percentile rank straight to 0–100 means the lowest
track in a small batch scores zero, which exaggerates real differences. Map to 0.2–1.0.

Hook immediacy is weighted highest because it is the metric most directly tied to whether
a playlist listener stays — and it is genuinely measurable, unlike "catchiness".

### Weight by measured discrimination, not by intuition

The "spread measured" column above is the range each metric actually produced across a
real 30-track batch, as a share of its own maximum. It is the deciding number.

**Stereo width scored full marks on 29 of 30 tracks.** One generator's output has
consistent width, so those points were a constant added to every track — contributing
nothing to the ranking while diluting the metrics that do separate tracks. Its budget
moved to hook, motif and spectral balance; it stays at a low weight purely as a guard, so
a genuinely mono or out-of-phase track still loses something.

Reweighting widened the score spread (σ 14.7 → 15.7) and **changed zero take selections** —
which is the outcome you want. If reweighting flips many decisions, the weights were
arbitrary; if it sharpens the distribution while the choices hold, they were not.

These weights are tuned to one generator. On different material they may not hold, so the
report prints the discrimination table for every run:

| Metric | Weight | Mean | Spread | |
|---|---|---|---|---|
| spectral | 15 | 10.5 | 93% | 🟢 good |
| hook | 24 | 15.7 | 92% | 🟢 good |
| … | | | | |
| stereo | 3 | 3.0 | 13% | 🔴 near-constant |

Anything marked near-constant on your batch is weight better spent elsewhere.

Two things the report itself has to get right, both learned by breaking them: escape
markdown metacharacters in any cell holding a generator-supplied title — one pipe silently
breaks the table for every row below it — and look verdict icons up with a default, or a
newly added verdict string crashes report generation on precisely the batches it was
added for. For the
percentile-ramped metrics the table also prints raw spread, and marks them *flattened*
when the batch had nothing real to rank on.

**Codec does not affect the measurements.** The same source as WAV, FLAC, MP3 (320/128/64k)
and AAC 96k produced raw metrics agreeing to within 5%, and identical spectral balance —
analysis runs at 22.05 kHz, so every codec's high-frequency rolloff sits above the Nyquist
limit and is simply not seen. Mixed-format batches are safe.

## Three grades

| | Meaning |
|---|---|
| 🟢 GREEN | No defects |
| 🟡 YELLOW | Something to check — hard cut, spectral seam, tempo far from target, possible vocals |
| 🔴 RED | A defect that cannot be intentional — regenerate |

Plus a separate **spot-check list** of timestamps that are ambiguous and don't affect grade.

## Getting the audio

Web generators don't always offer bulk download. Rather than clicking through 30 files,
capture the URLs the player itself requests during playback and fetch them directly.

Two things that break a naive version of this:

- **Autoplay contamination.** When a track finishes, the player advances and fetches the
  next file, which then gets attributed to the wrong track. Pause everything before each
  click, and accept only the *first* audio request after the click.
- **Labels change under you.** A play button's label becomes "Pause" while playing. Capture
  every track's title when you enumerate the buttons, not inside the loop.

**One dead link must not lose the batch.** Generator URLs expire, and mapping a fetch
function over a thread pool propagates the first exception out of the whole run —
measured, a single 404 aborted everything with a bare traceback, discarding the 6 of 7
files that had already downloaded and producing no report at all. Collect per-file
failures, name them, carry on with what arrived, and record the gap in the report so
nobody wonders why the episode is short. Abort only when nothing downloaded.

**Cache partial downloads safely.** Write to a temporary name and rename on success. A
process killed mid-download otherwise leaves a partial file that passes any plausible size
check — a 20%-truncated 3 MB track is still 611 KB — and is then treated as a valid cache
entry forever, failing to decode on every later run. Pair that with deleting a downloaded
file that fails to decode, so the next run refetches it instead of reporting the same
error indefinitely. Only delete files the tool fetched itself, never ones the user pointed
it at.

On format: these services typically serve compressed audio (AAC in an `.m4a` container)
rather than WAV. That's fine. At the bitrates in use the difference from lossless is
inaudible, and YouTube re-encodes everything on upload anyway, so a lossless master's
advantage doesn't survive the platform pipeline.

## Cost

Screening a 30-file episode takes about half a minute end to end, so it is cheap enough
to run on every batch rather than only when something sounds wrong.

Almost all of it is ffmpeg, not analysis: measured per track, decoding is 12% of the time
and the numpy work 14%, while the **EBU R128 loudness pass is 73%**. Since that is
subprocess wait, running tracks across a thread pool gives a near-linear speedup —
24.1s to 7.6s on four threads, with byte-identical results.

## Implementation

Working code: [`tools/track-picker/`](../tools/track-picker/)

```bash
python3 run.py --dir ./audio --out ./report --episode "Episode Name"
```

Produces a Markdown report with grades, scores, spot-check timestamps, and a proposed
playlist order. Requires Python 3.9+, numpy, and ffmpeg.
