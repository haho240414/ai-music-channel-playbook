# Episode brief — <EPISODE TITLE>

Fill this in before writing any prompts. Both the music prompts and the cover prompt
inherit from it, which is what keeps them from contradicting each other.

## Identity

| Field | Value |
|---|---|
| Episode title | |
| Place | |
| Time of day | |
| **Season** | |
| Track count | 12–15 |
| Runtime target | |

> Season is set here and nowhere else. A cover in summer light with a track about falling
> snow is the most common shipping error.

## Listener experience

One paragraph. What someone hears who knows nothing about the series and never reads the
description.

## Sound ratio

**Shared identity (70–80%)** — the instruments and production that make every episode of
this channel sound related:

**Episode color (20–30%)** — what makes *this* episode distinguishable. Texture, space,
tempo range, light. Not a genre change.

## Global prompt

Appended to every track prompt in this episode.

> Instrumental <genre>, no vocals, no spoken word, no choir, no <adjacent genre>, no
> <adjacent genre>, no <production cliché>. <Lead instruments>, <drums>, <bass>,
> <texture>. Make the first 5–10 seconds musically attractive and immediately playable.
> Keep the track complete, <adjective>, <adjective>, and <adjective>.

## Recurring motif (optional)

If the channel carries one, name it and limit it to 2–3 tracks.

| Field | Value |
|---|---|
| Motif | |
| Stated in tracks | |
| All other tracks | Must not state it clearly |

## Tracklist

Plan keys and BPM up front so the finished episode can be sequenced harmonically.

| # | Title | BPM | Key | Hook instrument / arrival | Motif |
|---|---|---|---|---|---|
| 01 | | | | within Ns | |
| 02 | | | | within Ns | |
| 03 | | | | within Ns | |
| 04 | | | | within Ns | |
| 05 | | | | within Ns | |
| 06 | | | | within Ns | |
| 07 | | | | within Ns | |
| 08 | | | | within Ns | |
| 09 | | | | within Ns | |
| 10 | | | | within Ns | |
| 11 | | | | within Ns | |
| 12 | | | | within Ns | |

## Narrative order (optional)

For the sequencer, if the episode has a progression. 0.0 = opens the episode, 1.0 = closes.

```json
{
  "First Track Title": 0.05,
  "Middle Track Title": 0.5,
  "Closing Track Title": 1.0
}
```

## Title / returned-name mapping

Fill in as tracks come back — generators rename silently.

| # | Prompted title | Returned as |
|---|---|---|
| | | |

## Publishing

| Field | Value |
|---|---|
| Searchable title | `<MOOD TITLE> — <music promise> \| <SERIES>` |
| Thumbnail lockup | `<MOOD TITLE>` / `<GENRE · PLAYLIST>` |
| Episode number | Description and filenames only — never the thumbnail or title start |
