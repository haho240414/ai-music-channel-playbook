# Running the generator

The prompts are only half of it. Submitting twelve to twenty prompts through a web
generator has its own failure modes, and losing track of what came back costs more time
than writing the prompts did.

This is the operating loop, written for an agent or a person driving a browser.

## One prompt per message, and wait

Submit a single track prompt, wait for it to finish, then submit the next. Queueing
several into one message produces one blended track or a refusal.

"Finished" means the track cards have appeared — usually two, one per take. A progress
percentage or a "creating…" status means it is still working.

## Verify the submission actually happened

The most common silent failure: the text lands in the input box, the send click does not
register, and you wait patiently for a track that was never requested.

After clicking send, confirm **one** of these before waiting:

- The prompt now appears in the conversation as a submitted message
- A generating/progress indicator is visible
- The input box is empty again

If the text is still sitting in the box, click send again. On a stubborn one, take a
screenshot and click the send control by coordinate rather than by accessibility label —
the label sometimes resolves to a stale element.

## Rotate sessions every ~4 tracks

Around the fourth or fifth prompt in one continuous session, generation starts failing
with internal errors. Starting a fresh session is much cheaper than retrying.

Navigate to the service's home URL to start a clean session. Avoid an in-page "new
session" control if it redirects unpredictably — a plain navigation is more reliable than
a client-side route change, which can restore prior session state faster than the next
action can run.

## Record what came back, immediately

Generators rename tracks. Keep the mapping as you go:

| # | Prompted title | Returned as | Takes |
|---|---|---|---|
| 02 | Second Avenue Drift | Glass Avenue / Transit Lights | 2 |
| 05 | Blue Hour Underpass | Indigo Drift | 1 |

Reconstructing this afterward from audio alone is miserable, and the tracklist, chapter
timestamps, and filenames all depend on it.

Also record, per track:

- **The tag string** the generator echoes back — check it contains `instrumental` on an
  instrumental channel
- **How many takes** returned; one take instead of two usually means a partial failure

## Failure recovery

| Symptom | Response |
|---|---|
| Generation error, first time | Click the retry control once |
| Same error, second time | **Rename the track concept** and resubmit — a prompt can be poisoned by its own title, and the same request under a new name succeeds |
| Only one take returned | Accept it; the screening tool handles uneven take counts |
| Returned tags omit `instrumental` | Regenerate with the voice exclusions moved to the front of the negative list |
| Page state jumps to an unrelated session | Navigate to the home URL and re-enter rather than fighting the router |

## Do not judge the audio while generating

It is tempting to listen and re-prompt as you go. Don't — you cannot compare takes
reliably one at a time, and half of what sounds wrong on first listen is a defect the
screening tool will identify precisely.

Generate the full episode, then run [`track-picker`](../tools/track-picker/), then listen
only to the shortlist.

## Harvesting the audio

When the episode is complete, run [`collect.js`](../tools/track-picker/collect.js) in the
generator's tab to recover the audio URLs, then hand the JSON to `run.py --urls`.

Two things that break a naive version of this are documented in
[quality screening](03-quality-screening.md#getting-the-audio): autoplay contaminating the
next track's URL, and play-button labels flipping to "Pause" mid-scan.

## Checklist per track

- [ ] Prompt submitted and confirmed (not still sitting in the box)
- [ ] Generation finished — track cards visible
- [ ] Returned title recorded, especially if renamed
- [ ] Tag string checked for `instrumental`
- [ ] Take count recorded
- [ ] Session rotated if this was the fourth prompt
