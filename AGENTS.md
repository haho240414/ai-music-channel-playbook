# Agent instructions

You are working inside the **AI Music Channel Playbook** — a method for producing
instrumental playlist channels with AI music generators.

## On your first message in this repo

Greet the user with this menu, then wait for them to choose. Keep it short; do not
summarize the docs unprompted.

```
This repo is a playbook for building instrumental playlist channels with AI music
generators. What would you like to do?

  1. Start a new channel        — decide identity, character, palette, sound
  2. Plan an episode            — brief + tracklist with keys and BPM
  3. Write song prompts         — expand a brief into per-track prompts
  4. Write cover art prompts    — cover plate, clean plate, loop
  5. Screen generated tracks    — defect check, take selection, sequencing
  6. Just explain the method

If you already have a channel, tell me its genre, place, character, and palette and
I'll work from that.
```

## Reading order

Do not read everything. Load what the task needs.

| Task | Read |
|---|---|
| 1, 2 | `templates/episode-brief.md`, `examples/01-episode-brief.md` |
| 3 | `docs/01-song-prompting.md`, `examples/02-song-prompts.md` |
| 4 | `docs/02-thumbnail-prompting.md`, `templates/character-bible.md`, `examples/03-` and `04-` |
| 5 | `docs/03-quality-screening.md`, `docs/04-playlist-sequencing.md`, `tools/track-picker/README.md` |
| Driving a generator | `docs/05-running-the-generator.md`, `docs/06-browser-automation.md` |
| Rendering the video | `docs/07-rendering-the-video.md` |

`examples/` is a complete filled-in episode. When the user is unsure how specific to be,
show them the relevant part of it rather than explaining.

## Non-negotiables

These are the rules the method rests on. Do not quietly drop them.

1. **Every song prompt has all seven parts** — title, tempo+key, hook with an arrival time
   in seconds, texture, one scene sentence, negative list, length. A missing part is a
   drift you will get back.
2. **The negative list does more work than the positive one.** Always include voice terms,
   adjacent genres, and production clichés.
3. **The hook line names an instrument and a deadline.** "Catchy" is not a instruction;
   "clean-guitar hook within 5 seconds" is.
4. **The character bible is pasted verbatim.** Paraphrasing it across episodes is how a
   recurring character becomes a different person.
5. **Never let an image model render title text.** Always add `no generated lettering, no
   readable signage, no logo, no watermark`, and add the title as a separate layer.
6. **Season lives in the brief.** Music and cover art both inherit it. Never let a track
   subject contradict the cover's season.
7. **RED is only for defects that cannot be intentional.** Do not grade a track down for
   something a producer might have chosen.

## What you cannot do

Say so plainly rather than implying otherwise:

- **You cannot hear audio.** No listening, no judging whether a track is good, no
  comparing takes by ear. The screening tool measures defects and objective properties;
  it produces a shortlist, not a verdict.
- **Subjective appeal, emotional fit, and thematic suitability are not measurable.** Hand
  those back to the user.

## When a brand rule needs breaking

An episode sometimes needs something the channel's rules exclude. That is allowed, but:

1. Surface the conflict **before** generating and get an explicit decision
2. Record the exception in that episode's own doc, scoped to that episode
3. Leave a pointer next to the rule itself in the channel doc

Do not silently break the rule, and do not silently "fix" an exception someone else made.

## Running the tooling

```bash
python3 tools/track-picker/run.py --dir ./audio --out ./report \
  --episode "Episode Name" --narrative narrative.json \
  --export --require-instrumental
```

Needs Python 3.9+, numpy, and ffmpeg (`FFMPEG_BIN` overrides the path). Full options in
`tools/track-picker/README.md`.

## Style

Match the docs: state the reasoning, not just the conclusion. Most rules here exist
because a specific failure happened, and the failure is the useful part.
