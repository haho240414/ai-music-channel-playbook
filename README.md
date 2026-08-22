# AI Music Channel Playbook

A working method for producing instrumental playlist channels with AI music generators —
prompt anatomy, cover-art prompting, automated defect screening, and playlist sequencing.

This is not a theory post. Every rule here comes from producing episodes of 15–20 tracks
at a time and hitting the failure modes that only show up at that volume.

## What's in here

| Doc | What it covers |
|---|---|
| [Song prompting](docs/01-song-prompting.md) | The seven-part prompt that reliably produces usable tracks, plus the failures that shaped it |
| [Thumbnail prompting](docs/02-thumbnail-prompting.md) | Keeping one character consistent across dozens of covers; why title text must be a separate layer |
| [Quality screening](docs/03-quality-screening.md) | Detecting broken tracks automatically — and being honest about what a machine cannot judge |
| [Playlist sequencing](docs/04-playlist-sequencing.md) | Picking track 1, ordering the rest, and why loudness normalization goes *down* |

Blank templates are in [`templates/`](templates/), and [`examples/`](examples/) has all of
them filled in for one complete episode. A working implementation of the screening and
sequencing tooling is in [`tools/track-picker/`](tools/track-picker/).

## What this is and isn't

Two halves, with very different levels of automation:

**The tooling runs by itself.** Point [`track-picker`](tools/track-picker/) at a folder of
audio and it screens, scores, picks between takes, sequences, and level-matches without
supervision.

**The prompting half is a method, not a machine.** There is no code here that invents a
style, picks a topic, or writes your tracklist. The templates have blanks in them, and
filling those blanks is the creative work. What the docs give you is the *shape* of a
prompt that works and the list of failures to design around.

So: this will not reproduce anyone's channel. It will let you build your own on the same
scaffolding.

## Using it with an LLM

The templates are designed to be filled by a language model with the docs in context.
That is the intended workflow, and it is why the docs state their reasoning rather than
just their conclusions.

1. Give the model [`docs/01-song-prompting.md`](docs/01-song-prompting.md),
   [`docs/02-thumbnail-prompting.md`](docs/02-thumbnail-prompting.md), and the
   [worked example](examples/).
2. Describe your channel — genre, place, character, palette, season — and ask it to fill
   [`templates/episode-brief.md`](templates/episode-brief.md).
3. Have it expand the brief into per-track prompts, checking each against the seven-part
   skeleton and the negative-list groups.
4. Generate, then run the screening tool on the results.

Steps 2 and 3 are where the judgment lives: deciding that this episode is a winter branch
line at dusk rather than a summer riverside, that the hook should be a fingerpicked guitar
rather than a Rhodes, that track 7 carries the motif fragment. A model can do that well
with the method in front of it. Neither the method nor the model does it unprompted.

## The core problem

AI music generators are good enough to produce a listenable track from a sentence.
They are not good enough to produce **fifteen tracks that belong on the same playlist**.

Generate an episode's worth and you get:

- Tracks that drift off-genre because the prompt didn't say what to avoid
- Two takes of every prompt, one of which is often subtly broken
- Loudness varying by 3–4 LU, so the listener rides the volume knob
- A cover image whose season contradicts the music's season
- Titles the generator silently renamed on you

The method here exists to catch all of that before publishing.

## The pipeline

```
episode brief  ← the only place season, palette, and identity are decided
     │
     ├─→ song prompts (one per track, from a shared global prompt)
     │        │
     │        └─→ generator → 2 takes per track
     │                 │
     │                 └─→ automated screening → GREEN / YELLOW / RED
     │                          │
     │                          └─→ take selection → sequencing → loudness normalization
     │
     └─→ cover prompt (character bible + scene + composition)
              │
              └─→ image generator → title text added as a separate layer
```

## Principles

**Say what to avoid, not just what you want.** The negative list does more work than the
positive one. Generators drift toward genre clichés unless you name them and exclude them.

**The first five seconds decide everything.** A playlist listener leaves before the track
develops. Every prompt states when the hook must arrive.

**Never let an image model render your title text.** It produces garbled pseudo-letters.
Generate a clean plate; add lettering as a layer.

**Automate the objective, keep the subjective human.** A script can prove a track has a
dropout at 18.8s. It cannot tell you whether the track is any good. Conflating those two
makes a tool nobody trusts.

**When a rule gets broken deliberately, write down that it was deliberate.** Otherwise the
next person "fixes" it back.

## Scope

The examples use fictional channels. The methodology is generator-agnostic — it was
developed against [Flow Music](https://flowmusic.app) but the prompt anatomy applies to
any text-prompted music model, and the screening tools work on any audio files.

## License

[MIT](LICENSE)
