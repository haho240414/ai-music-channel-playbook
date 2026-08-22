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

Templates for each are in [`templates/`](templates/). A working implementation of the
screening and sequencing tooling is in [`tools/track-picker/`](tools/track-picker/).

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
episode brief
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
