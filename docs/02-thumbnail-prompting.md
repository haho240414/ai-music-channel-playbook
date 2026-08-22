# Thumbnail prompting

Cover art for a playlist channel has a harder job than a one-off illustration: the same
character has to appear across dozens of episodes and still read as the same person, while
the setting changes every time.

## The eight-part cover prompt

```
1. STYLE       Medium and rendering style, stated first.
2. CHARACTER   The character bible, copied verbatim from the channel doc.
3. SCENE       Place, grounded in specific real detail.
4. WEATHER     Season, light, and atmosphere — matched to the music.
5. COMPOSITION Character placement and the title-safe zone.
6. PALETTE     Brand colors, named.
7. NEGATIVE    What must not appear.
8. FORMAT      Aspect ratio.
```

Worked example:

> A polished 2D animated illustration, hand-painted texture, in the <SERIES> style. Same
> recurring character: a woman in her early-to-mid 20s, long straight black hair with neat
> bangs, calm and contemplative expression, wearing a modern cobalt blue casual summer
> outfit with deep navy headphones around her neck, positioned on the right side of the
> frame, walking slowly along an old stone wall path in strong summer afternoon light.
>
> Background: a weathered gray stone wall stretching into the distance, its sharp dark
> shadow cutting across the path under high summer sun, lush deep-green summer trees
> overhanging the wall, faint heat haze shimmer above the stone tiles.
>
> Color palette: cobalt blue, deep navy, cream, warm amber, deep summer green — no pastel
> spring tones.
>
> Composition: character on the right, generous negative space on the left for title text.
>
> No excessive neon, no cyberpunk elements, no dark night exposure. Strong, warm, humid
> summer daylight, high contrast shadows. 16:9 thumbnail composition.

## The character bible

The single most important artifact. Write it once, then paste it **verbatim** into every
cover prompt. Paraphrasing is how a character slowly becomes a different person over ten
episodes.

A usable bible fixes:

- **Age band** — "early-to-mid 20s", not "young"
- **Hair** — length, color, and the distinguishing detail (bangs, parting, ponytail)
- **Expression** — the default emotional register
- **One fixed prop** — the thing that identifies them at thumbnail size
- **Clothing impression** — color family, not a specific outfit
- **Frame position** — same side every time

The fixed prop does the heavy lifting. At thumbnail scale a face is roughly 40 pixels
tall; nobody recognizes it. A distinctive silhouette element — headphones around the neck,
a particular bag, a camera — is what makes an episode recognizable in a subscription feed.

Template: [`templates/character-bible.md`](../templates/character-bible.md)

### Multiple characters

If a series has more than one recurring character, give each their own bible and their own
fixed prop, and decide in advance which episodes they appear in. Keep them visually
separable at small size — different prop categories, not two variations of the same prop.

## Grounding the scene

Generic prompts produce generic postcards. Compare:

| Vague | Grounded |
|---|---|
| an old Asian street | narrow deep shopfronts with mismatched façades, a covered walkway built for rain, wet charcoal pavement under warm tungsten |
| a Korean palace | a weathered gray stone wall stretching into the distance, curved tiled roofline at the upper edge |

Research what actually makes the place look like itself — the architectural adaptation, the
practical detail — and name that. Two or three concrete nouns beat any number of adjectives.

**Exclude the landmark.** Named monuments pull the model toward tourist-brochure framing.
Ask for the side street, not the postcard.

## Season must match the music

This is the failure that is easiest to ship and most embarrassing to discover later.

A real case: an episode's cover art was drafted with cherry blossoms while one of its
tracks was explicitly about cherry blossom petals — then the episode was rescheduled into
summer. The image was updated to deep green foliage, heat haze, and hard shadows, but the
*track* was still a spring track. It had to be regenerated as a summer subject to match.

**Season is a property of the episode, not of the image.** Fix it in the brief and let both
the music prompts and the cover prompt inherit it. Checklist:

- Foliage state
- Light quality and shadow hardness
- Clothing weight
- Any seasonal props (fans, umbrellas, scarves)
- **Track subjects** — no seasonal imagery in titles that contradicts the cover

## Composition and the title-safe zone

- Character on one side, consistently. Pick a side for the series and never flip it.
- Reserve **40–45% of the frame** on the opposite side as clean space for the title.
- Background should carry at least half the image; a portrait with a blurred backdrop
  reads as a music single, not a place-based playlist.
- 16:9.

## Never let the model render your title text

Image models produce garbled pseudo-lettering. Every cover prompt ends with an instruction
against generated text:

```
No generated lettering, no readable signage, no logo, no watermark.
```

Then produce **two plates**:

1. **Cover plate** — with the character, title-safe space left empty
2. **Clean plate** — no character, no text, for loop video backgrounds

Add the title as a separate text layer afterward, in a real typeface. This also means you
can change the title without regenerating the art.

Typical lockup:

```
EPISODE MOOD TITLE
GENRE · PLAYLIST
```

Keep episode numbers off the thumbnail. They belong in the description and filenames —
a visible "EP.07" tells a new viewer they are late to something.

## The negative list

Same principle as [song prompting](01-song-prompting.md#6-negative-list--do-not-skip-this).
Four groups:

- **Text**: `no generated lettering, no readable signage, no logo, no watermark`
- **Tourist clichés**: the named landmarks and postcard framings for your setting
- **Style drift**: `no excessive neon, no cyberpunk, no dark night exposure` — whatever your
  brand isn't
- **Extra people**: `no extra foreground characters` — models add crowds unprompted

## Loop video plates

For a looping background video, generate the clean plate and animate narrowly:

> Create a 12-second seamless loop. Locked eye-level camera, no cuts, no zoom, no parallax
> jump. Animate only two puddle ripples, soft distant rainfall, warm lamp flicker, and
> barely perceptible clothing movement. Keep face, pose, and props stable. First and last
> frames must match. No text, logo, readable signage, sudden weather change, or dramatic
> action.

Naming exactly what may move is what keeps a loop from breathing or morphing. Everything
not on the list should be declared stable.

## Deliberate rule breaks

Sometimes an episode needs something the brand rules exclude — a setting you'd normally
avoid, a prop that isn't in the palette. That's fine. What is not fine is a future reader
finding the violation and silently "correcting" it.

Protocol:

1. Surface the conflict before generating, and get an explicit decision
2. Record the exception in that episode's own doc — what rule, why, and that it is scoped
   to this episode only
3. Leave a pointer **at the rule itself** in the channel doc:

```markdown
- Avoid tourist-landmark symbols in base imagery
  (⚠️ Exception: EP05 uses landmark imagery by explicit approval —
  see episodes/05/IMAGE_NOTES.md)
```

Without step 3, the exception is invisible from where the rule lives, which is exactly
where someone will read it.

Template: [`templates/thumbnail-prompt.md`](../templates/thumbnail-prompt.md)
