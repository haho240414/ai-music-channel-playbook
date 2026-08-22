# Worked example — PLATFORM FOUR

Every template in [`templates/`](../templates/) filled in for one complete episode, with
nothing left blank.

The channel is invented. It exists so you can see what a finished brief, a full set of
song prompts, a character bible, and a cover prompt actually look like — the templates on
their own don't show you how much specificity is enough.

## The channel

| | |
|---|---|
| Series | **PLATFORM FOUR** |
| Premise | Instrumental music for slow regional train journeys |
| Genre | Slow-travel folk — fingerpicked acoustic guitar, felt piano, brushed drums, warm analog pad |
| Tempo band | 68–92 BPM |
| Character | A man in his early 30s with a green enamel thermos, always on the **left** of frame |
| Palette | Moss green, oat cream, rust, slate blue |
| Episode | **LAST TRAIN, FIRST SNOW** — winter dusk, 12 tracks |

## Read in this order

| File | What it shows |
|---|---|
| [01-episode-brief.md](01-episode-brief.md) | The brief everything else inherits from — season, sound ratio, global prompt, key plan |
| [02-song-prompts.md](02-song-prompts.md) | All 12 track prompts, complete and submittable |
| [03-character-bible.md](03-character-bible.md) | The recurring character, written to be pasted verbatim |
| [04-thumbnail-prompts.md](04-thumbnail-prompts.md) | Cover plate, clean plate, loop, and the title layer |
| [05-narrative.json](05-narrative.json) | Semantic order for the sequencer |

## Using it

Copy the whole folder, then change one layer at a time:

1. **Keep the structure, change the identity.** Swap genre, palette, character, and place
   in the brief. The seven-part prompt shape and the negative-list discipline carry over.
2. **Regenerate the tracklist** for your own place and season.
3. **Run the screening**:

```bash
python3 ../tools/track-picker/run.py \
  --dir ./audio --out ./report \
  --episode "LAST TRAIN, FIRST SNOW" \
  --narrative 05-narrative.json \
  --export --require-instrumental
```

## Why this example looks the way it does

Some choices are deliberate demonstrations rather than taste:

- **The negative list names folk-adjacent drift** (`no bluegrass banjo breakdown, no celtic
  reel`) because that is where a generator wanders when you ask for fingerpicked acoustic
  guitar. Your negative list should name *your* genre's neighbours, discovered by leaving
  them out once and hearing what comes back.
- **Two tracks contain closer keywords** — "Last Announcement" (track 10) and "Going Home
  in the Dark" (track 12). The sequencer ranks hints by specificity, so the 10-character
  `going home` wins over the 4-character `last`, and the right track closes. This is the
  bug described in [playlist sequencing](../docs/04-playlist-sequencing.md#pick-the-closer-before-the-opener).
- **The tempo band is 68–92**, well below the 88–118 used elsewhere in the docs, to show
  that none of the method depends on a particular tempo range.
