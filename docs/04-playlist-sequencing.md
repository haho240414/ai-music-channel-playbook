# Playlist sequencing

Once the broken tracks are out, the remaining decisions are which take to keep, what order
to play them in, and how to make them sit at the same volume.

## Take selection

Group by title, keep the highest-scoring non-RED take, drop the rest. Record what was
dropped and why — you will want to revisit it when a track feels weak later.

Two cautions, both observed in real output:

**Strip take markers before grouping.** They appear in filenames (`_take2`, `_a`, `_b`,
`-2`) *and* in titles the generator returns (`Sidestreet Weather (Take 2)`). Without
normalizing both, two takes of one track become two tracks and both end up in the episode.

**Normalize the displayed title as well.** The winning take is frequently the one labelled
`(Take 2)`; if only the grouping key is normalized, that suffix reaches the tracklist,
the exported filename, and the published chapter timestamps.

## Track 1

The most consequential position. Two competing pulls:

- **The best track overall** — highest total score
- **The best opener** — the one that grabs fastest

These are not the same track. In one episode the top-scoring track took 7.6 seconds to
reach full energy; another reached it in 2.7 seconds with a strong hook. The second one
opens.

Weight the opener decision heavily toward hook immediacy, with a hard penalty past ~5
seconds:

```
value = 0.5 × total_score + 40 × hook_ratio
if time_to_full > 5s:  value ×= 0.6
if time_to_full > 8s:  value ×= 0.3
```

## Pick the closer *before* the opener

Order of operations, not a detail.

An episode usually has a track that is semantically its ending — the walking-home track,
the closing-up track. If you select the opener first, and that track happens to have the
highest score, it gets locked into position 1 and is no longer available to close. This
happened: a track literally prompted as the episode's closing track was placed first
because its numbers were good.

Choose the closer first, remove it from the pool, then choose the opener from what remains.

When matching closer hints by title keyword, **rank matches by specificity**. A short
keyword like `last` matched `Chairs Stacked, Lights Off` before the intended
`The Long Way Home` ever got compared. Prefer the longest matching hint.

## Ordering the middle

Greedy nearest-neighbor over a transition cost:

```
cost = 0.35 × |ΔBPM| / 10
     + 0.35 × camelot_distance × key_confidence
     + 0.20 × |Δenergy|
     + 0.10 × |Δbrightness|
     + 0.60 × |energy − target_arc(position)|
     − score / 100
```

**Key distance** uses the Camelot wheel: same key 0, adjacent or relative major/minor 1,
further apart more. Standard DJ harmonic mixing.

**Weight key distance by confidence.** Key estimation is correlation against major/minor
profiles, and its reliability varies enormously — across one batch the margin between the
best and second-best key ranged from 0.29 (certain) down to 0.027 (a coin flip). Scaling
the key term by that margin stops the sequencer from optimizing against noise. Mark
low-confidence estimates in the report so a human knows not to trust them.

#### Don't bother trying to make key detection more confident

Tempting, and measured to be a dead end. Across 30 real tracks, five aggregation
strategies and two frequency bands:

| Aggregation | Mean margin | Tracks below 0.20 |
|---|---|---|
| Median over frames (baseline) | 0.109 | 23 / 30 |
| Mean over frames | 0.119 | 25 / 30 |
| Energy-gated frames | 0.113 | 26 / 30 |
| Per-frame whitening | 0.122 | 23 / 30 |
| Spectral peaks only | 0.120 | 25 / 30 |

Narrowing the band from 55–2200 Hz to 110–1760 Hz made every variant equal or worse.
Nothing moves the needle: dense, reverberant, chord-extension-heavy material simply does
not yield a confident single key. Spend the effort on handling the uncertainty rather
than removing it.

**And the discounted key term still earns its place.** Ablating it on a real episode:

| | Σ key distance | Σ \|ΔBPM\| |
|---|---|---|
| Key ignored | 30 | **60** |
| Confidence-weighted (default) | 24 | 68 |
| Doubled weight | **20** | 74 |

At a mean confidence of 0.50 the term still pulls key distance down meaningfully, trading
a little tempo smoothness for it. Confidence weighting discounts the signal; it does not
switch it off, which is the intended behaviour.

**Energy arc** rises gently to a peak around 60% through, then descends:

```
position 0%   ▁▂▃  0.75   opens strong
position 60%  ▇█▇  0.90   peak
position 100% ▂▁   0.25   resolves
```

**The `− score/100` term** is a weak pull bringing better tracks earlier, without letting
score override musical continuity.

### Make the tempo and key penalties superlinear

Not linear. With a linear cost the optimizer will happily accept one jarring transition
in exchange for several tiny improvements elsewhere, because the arithmetic says that is
a net win. Perceptually it is not: a listener notices a 27 BPM lurch between tracks and
does not notice five 5 BPM steps.

```
bpm_term = W_BPM × (|ΔBPM| / 10) ** 1.7
key_term = W_KEY × camelot_distance ** 1.5 × key_confidence
```

Exponents above 1 make outlier transitions expensive enough to avoid rather than
amortize.

### Polish the greedy result

Greedy nearest-neighbour commits early and spends the good transitions at the front, so
the tail of a real episode inherits whatever is left. On a 14-track episode the greedy
tail carried BPM jumps of 15, 15 and 16 and a key distance of 4 on the final transition.

Run a local improvement pass afterward — 2-opt segment reversals plus single-track
relocations, accepting any move that lowers total cost. **Keep position 1 and the last
position fixed**: both were chosen deliberately and are not the optimizer's to overrule.

Measured on that same 14-track episode:

| | Σ\|ΔBPM\| | max \|ΔBPM\| | jumps > 12 BPM | Σ key distance |
|---|---|---|---|---|
| Greedy, linear cost | 103 | 16.0 | 3 | 27 |
| \+ local improvement | 100 | **26.7** | 3 | 23 |
| \+ superlinear cost | **61** | **9.9** | **0** | **23** |

Note the middle row: the improvement pass on its own made the worst transition *worse*.
Both changes are needed — the search finds better arrangements, and the exponent tells it
which arrangements are actually better.

## Semantic order

Signal analysis cannot know that "Chairs Stacked, Lights Off" is an ending image. If the
episode has a narrative or a time-of-day progression, supply it explicitly — a mapping from
title to a 0.0–1.0 position — and add a term for distance from the intended slot.

Keep the weight moderate. It should break ties and prevent obvious absurdities, not
override the musical flow.

## Loudness normalization

The part most likely to be done backwards.

An episode measured 3.6 LU apart between its quietest and loudest track — enough that a
listener reaches for the volume between tracks.

**The obvious approach fails.** Targeting −14 LUFS and raising each track toward it barely
helped: 3.6 LU → 3.3 LU. AI-generated tracks arrive already peak-limited near full scale,
so raising a quiet track immediately hits the true-peak ceiling and the gain gets clamped —
differently for every track. The spread survives.

**Normalize down instead.** For each track compute the highest LUFS it could reach without
exceeding the true-peak ceiling:

```
achievable_i = lufs_i + (ceiling_dBTP − true_peak_i)
```

Take the minimum across the episode as the common target. The safety guarantee is
per-track rather than a sign check:

```
gain_i = common − lufs_i ≤ achievable_i − lufs_i = ceiling − true_peak_i
```

so no track's true peak can exceed the ceiling. Most gains come out negative; the track
that *sets* the minimum gets a small positive gain if it had peak headroom, which is
intended and provably safe. Every track lands at exactly the same loudness.

Result on the same episode: **3.6 LU → 0.10 LU**, all true peaks safely under −1 dBTP.

The absolute level ends up lower than −14 LUFS, and that is fine — YouTube normalizes
playback loudness anyway. Consistency across the episode is what matters; absolute level
is not preserved through the platform regardless.

Use **plain gain**, not a dynamics processor. A limiter or `loudnorm`-style two-pass
compression changes the mix; a gain change does not.

## Deliverables

Once ordered and normalized:

- Numbered audio files in play order
- An `.m3u` playlist
- **Cumulative timestamps** for the video description:

```
0:00 Kettle On, Lights Low
2:47 Second Avenue Drift
5:44 Rooftop, Half Past Six
```

Generate timestamps from the *normalized, ordered* files, not from the planning document —
actual durations drift from what was requested.

## Implementation

[`tools/track-picker/`](../tools/track-picker/)

```bash
python3 run.py --dir ./audio --out ./ep06 \
  --episode "Episode Name" \
  --narrative narrative.json \
  --export --require-instrumental
```
