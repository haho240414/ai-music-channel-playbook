# Song prompting

How to write a prompt that produces a track you can actually put on a playlist, and the
failure modes that shaped each rule.

## The seven-part prompt

Every track prompt has the same skeleton. Order matters less than presence — leave a part
out and you will get the drift it was there to prevent.

```
1. TITLE      Create an original instrumental <genre> track titled "<Title>,"
2. TEMPO/KEY  <N> BPM, <key>.
3. HOOK       <Instrument> <figure> within <N> seconds.
4. TEXTURE    <drums>, <bass>, <supporting instruments>, <production texture>.
5. SCENE      <One sentence of place and feeling.>
6. NEGATIVE   No <vocals>, no <adjacent genres>, no <production clichés>.
7. LENGTH     About three minutes.
```

Worked example:

> Create an original instrumental modern city jazz track titled "Kettle On, Lights
> Low," 88 BPM, D minor. Open with a four-note felt-piano figure within 4 seconds; let
> warm Rhodes shadow only the final leap. Brushed snare, soft kick, rounded bass,
> restrained rain shimmer. Private discovery, not a theme-song sting. No vocals, no spoken
> word, no choir, no bossa nova, no samba, no Latin clave, no EDM drop, no trailer music.
> Warm Rhodes or felt piano, dry intimate drums, restrained broken-beat pocket, tasteful
> jazz extensions, subtle analog texture. Keep the track complete, elegant, urban, and
> emotionally restrained. About three minutes.

### 1. Title in quotes

Put it in quotes and the generator usually adopts it. Usually — see
[titles get silently renamed](#titles-get-silently-renamed).

### 2. Tempo and key

State both. Key matters more than it looks: it is what lets you sequence the finished
episode harmonically instead of shuffling at random. Plan the keys at brief time, not
after the fact.

### 3. The hook line — the highest-leverage sentence

```
Open with a bright syncopated electric-piano motif within 4 seconds.
Spacious felt piano within 8 seconds.
Crisp Rhodes voicings within 5 seconds.
```

Playlist listeners leave during the intro. Without this line, models routinely spend
20–30 seconds on an ambient wash before anything identifiable happens.

Name **which instrument** carries the hook and **by when**. "Make it catchy" does nothing;
"clean-guitar hook within 5 seconds" does.

### 4. Texture list

Drums, bass, then supporting instruments, then production character. Keep it to things a
session player would understand. Adjectives that describe *playing* ("brushed", "muted",
"rim-click", "ghost notes") land better than adjectives that describe *vibe*.

### 5. Scene — exactly one sentence

One concrete image. `Capture a vendor's cart rolling away down the riverside road.` Two or more and the model starts arranging a narrative instead of a groove.

### 6. Negative list — do not skip this

This is the part people leave out, and it is the part that keeps an episode coherent.
Group it into three:

- **Voice**: `no vocals, no spoken word, no choir, no humming, no voice samples`
- **Adjacent genres the model will drift into**: for city jazz, `no bossa nova, no samba,
  no Latin clave`; for R&B, `no lo-fi crackle, no EDM drop`
- **Production clichés**: `no trailer music, no cinematic build, no club drop`

Pick the exclusions from what the model actually produced when you left them out. The list
above exists because each item happened.

### 7. Length

`About three minutes.` Without it, lengths scatter and your episode runtime becomes
unpredictable.

## The global prompt pattern

Writing all seven parts fifteen times is how episodes become inconsistent. Instead, define
one **global prompt** carrying the shared identity, and per-track lines carrying only what
differs.

Global (identical on every track in the episode):

> Instrumental modern city jazz, no vocals, no spoken word, no choir, no bossa nova, no
> samba, no Latin clave, no EDM drop, no trailer music. Warm Rhodes or felt piano, dry
> intimate drums, restrained broken-beat pocket, rounded bass, tasteful jazz extensions,
> subtle analog texture. Make the first 5–10 seconds musically attractive and immediately
> playable. Keep the track complete, elegant, urban, and emotionally restrained.

Per track (only title, tempo, key, hook, and scene):

> **Sidestreet Weather** — 90 BPM, E♭ major. Compact Rhodes ostinato within 5 seconds, clean
> broken beat, warm bass, muted guitar plucks, tiny wood-percussion flecks.

Append the global to each per-track line at submission time. A good ratio is roughly
70–80% shared identity, 20–30% per-track variation — enough that the episode sounds like
one record, enough that tracks stay distinguishable.

## Failure modes

These all happened. Each one costs an episode's worth of rework if you don't plan for it.

### Titles get silently renamed

Generators may return a track under a name they invented rather than the one you asked for.
In one 15-track episode, three came back renamed:

| Prompted | Returned as |
|---|---|
| Second Avenue Drift | Glass Avenue / Transit Lights |
| Blue Hour Underpass | Indigo Drift |
| Headlights in Minor | Neon Stride |

**Keep a mapping** from prompted title to returned title as you go. Reconstructing it later
from audio alone is miserable, and your tracklist, chapter markers, and filenames all
depend on it.

### Two takes per prompt, one often broken

Most generators return two variations. They are not equivalent — in one batch, take 2 of a
track had a dead-silent gap at 18.8s while take 1 was clean. Assume every prompt yields one
usable take and one coin flip, and screen both. See
[quality screening](03-quality-screening.md).

### Sessions degrade after a handful of prompts

Around the fourth or fifth prompt in one continuous session, generation starts failing with
internal errors. Rotate to a fresh session every ~4 tracks. This is cheaper than
retrying failures.

### A failing prompt can be poisoned by its own title

One prompt failed repeatedly with the same API error across multiple retries. Changing
nothing but the title — same BPM, same description — succeeded immediately.

If retries fail twice, **rename the track concept and resubmit** rather than retrying a
third time.

### Soft language instructions get ignored

For vocal tracks, this is unreliable:

```
singing simple English lyrics about a quiet morning
```

This works consistently:

```
The lyrics must be entirely in English, not Korean: a quiet morning...
```

An explicit imperative naming the language to *exclude* survives; a descriptive phrase does
not. The same asymmetry as the negative list.

### "No vocals" is not self-enforcing

Verify. Most generators echo back a tag string describing what they made — check that it
contains `instrumental` before accepting the track. On an instrumental-only channel, a
track with vocals is unusable no matter how good it is.

## Planning an episode

Decide these before writing a single prompt:

1. **Track count** — 12–15 is a workable playlist episode
2. **BPM spread** — cluster within ~30 BPM so sequencing has room but the record stays coherent
3. **Key plan** — assign keys up front so the finished episode can be ordered harmonically
4. **Which tracks carry any recurring motif** — if the channel has one, 2–3 tracks per
   episode is plenty; more makes it a jingle
5. **Season and time of day** — this must match the cover art. See
   [thumbnail prompting](02-thumbnail-prompting.md#season-must-match-the-music).

Template: [`templates/episode-brief.md`](../templates/episode-brief.md)
