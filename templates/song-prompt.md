# Song prompt template

## Skeleton

```
Create an original instrumental <GENRE> track titled "<TITLE>," <BPM> BPM, <KEY>.
<HOOK INSTRUMENT> <FIGURE> within <N> seconds.
<DRUMS>, <BASS>, <SUPPORTING INSTRUMENTS>, <PRODUCTION TEXTURE>.
<ONE SENTENCE OF SCENE AND FEELING.>
No <voice terms>, no <adjacent genres>, no <production clichés>.
About three minutes.
```

## Filled example

> Create an original instrumental modern city jazz track titled "Sidestreet Weather," 90 BPM,
> E♭ major. Compact Rhodes ostinato within 5 seconds, clean broken beat, warm bass, muted
> guitar plucks, tiny wood-percussion flecks. A narrow side street breathing after rain.
> No vocals, no spoken word, no choir, no bossa nova, no samba, no Latin clave, no EDM
> drop, no trailer music. About three minutes.

## Split form (recommended for a full episode)

Write the global once, the per-track line per track, concatenate at submission.

**Global**

```
Instrumental <GENRE>, no vocals, no spoken word, no choir, no <ADJACENT GENRE>,
no <ADJACENT GENRE>, no <PRODUCTION CLICHÉ>. <LEAD INSTRUMENTS>, <DRUMS>, <BASS>,
<TEXTURE>. Make the first 5–10 seconds musically attractive and immediately playable.
Keep the track complete, <ADJ>, <ADJ>, and <ADJ>.
```

**Per track**

```
<TITLE> — <BPM> BPM, <KEY>. <HOOK> within <N> seconds. <2–4 texture details>.
<Scene sentence.>
```

## Negative list starters

Adapt from what your generator actually produces when you omit them.

| Category | Terms |
|---|---|
| Voice | `no vocals, no spoken word, no choir, no humming, no voice samples, no rap` |
| Jazz-adjacent drift | `no bossa nova, no samba, no Latin clave, no tropical lounge` |
| Electronic drift | `no EDM drop, no club drop, no festival build` |
| Cinematic drift | `no trailer music, no cinematic build, no orchestral swell` |
| Texture drift | `no lo-fi crackle, no vinyl noise, no ambient wash` |
| Legal / ethical | `no artist imitation, no reference to existing songs` |

## Vocal tracks

If the channel does use vocals, an imperative naming the excluded language is far more
reliable than a descriptive phrase:

```
The lyrics must be entirely in <LANGUAGE>, not <OTHER LANGUAGE>: <subject>.
```

## Checklist before submitting

- [ ] Title in quotes
- [ ] BPM **and** key
- [ ] Hook instrument named, with an arrival time in seconds
- [ ] Drums, bass, supporting instruments listed
- [ ] Exactly one scene sentence
- [ ] Negative list covers voice + adjacent genres + clichés
- [ ] Length stated
- [ ] Rotate to a fresh session every ~4 tracks
- [ ] Record the returned title if it differs from the prompted one
- [ ] Confirm the returned tag string says `instrumental` (instrumental channels)
