# Playlist sequencing

Once the broken tracks are out, the remaining decisions are which take to keep, what order
to play them in, and how to make them sit at the same volume.

## Take selection

Group by title, keep the highest-scoring non-RED take, drop the rest. Record what was
dropped and why — you will want to revisit it when a track feels weak later.

One caution when inferring titles from filenames: strip take markers (`_take2`, `_a`, `_b`,
`-2`) before grouping, or two takes of the same track become two different tracks and both
end up in the episode.

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

**Energy arc** rises gently to a peak around 60% through, then descends:

```
position 0%   ▁▂▃  0.75   opens strong
position 60%  ▇█▇  0.90   peak
position 100% ▂▁   0.25   resolves
```

**The `− score/100` term** is a weak pull bringing better tracks earlier, without letting
score override musical continuity.

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

Take the minimum across the episode as the common target. Every gain is then negative, no
clipping is possible, and every track lands at exactly the same loudness.

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
