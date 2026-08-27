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

| Metric | Weight | What it measures |
|---|---|---|
| Hook immediacy | 22 | Time to reach full energy + onset density in the first 5s |
| Motif repetition | 18 | Self-similarity strength at phrase-length lags (5–30s) |
| Pulse clarity | 12 | Median beat-grid coherence |
| Spectral balance | 13 | Distance from the batch's median spectral profile |
| Dynamics | 13 | Crest factor and EBU R128 loudness range |
| Stereo width | 8 | Mid/side energy ratio |
| Loudness consistency | 14 | LUFS agreement with the batch, true-peak headroom |

Two design choices worth copying:

**Score relative to the batch, not to invented targets.** There is no correct spectral
balance for a genre. But a track that is a clear outlier *among its own episode* is worth
looking at. Comparing against the cohort median avoids fabricating numbers.

**Floor the relative metrics.** Mapping percentile rank straight to 0–100 means the lowest
track in a small batch scores zero, which exaggerates real differences. Map to 0.2–1.0.

Hook immediacy is weighted highest because it is the metric most directly tied to whether
a playlist listener stays — and it is genuinely measurable, unlike "catchiness".

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

On format: these services typically serve compressed audio (AAC in an `.m4a` container)
rather than WAV. That's fine. At the bitrates in use the difference from lossless is
inaudible, and YouTube re-encodes everything on upload anyway, so a lossless master's
advantage doesn't survive the platform pipeline.

## Implementation

Working code: [`tools/track-picker/`](../tools/track-picker/)

```bash
python3 run.py --dir ./audio --out ./report --episode "Episode Name"
```

Produces a Markdown report with grades, scores, spot-check timestamps, and a proposed
playlist order. Requires Python 3.9+, numpy, and ffmpeg.
