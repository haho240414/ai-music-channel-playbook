# Browser automation

Twelve to twenty prompts per episode is too many to submit by hand without losing track
of what came back. This is the technique for driving a web generator's browser tab
automatically — what we actually run, not a theoretical approach.

It assumes an agent (or a script) that can do four things to a browser tab: read the
accessibility tree, type into a field, click an element, and read the page's text. Claude
Code's browser tools work this way; so do Playwright and Selenium. The technique is the
same regardless of which one is driving.

## The core loop

For each track:

```
1. Locate the prompt textbox (accessibility-tree query, not a screenshot)
2. Set its value to the full prompt (global + per-track, concatenated)
3. Locate and click the send control
4. Verify the submission registered (see below) — retry once if not
5. Wait for generation to finish
6. Verify completion (see below)
7. Record the returned title and tag string
8. Move to the next track, or rotate sessions if this was the fourth
```

Step 4 is the step that gets skipped and causes the most wasted time. Clicking send does
not always register — the click can land before the button is interactive, or the text
can still be settling. Confirm the prompt now appears as a submitted message, or that a
generating/progress indicator appeared, before waiting. If the textbox still holds the
text, the send did not go through — click again.

## Verify cheaply first, screenshot only as a fallback

Every check has a cost. Order them from cheapest to most expensive:

1. **Accessibility-tree query** (find the send button, read a button's label) — cheapest,
   use by default
2. **Text extraction** (read the page's visible text to confirm a prompt was submitted or
   a generation finished) — cheap, and it doubles as a record of what the generator
   actually said back
3. **Screenshot** — only when the first two give an ambiguous or contradictory signal

A concrete case where this mattered: a send click appeared to succeed by every
accessibility signal, but the prompt never actually posted. A screenshot showed the text
still sitting in the input box, unsent. The fix was a raw coordinate click on the visible
send arrow rather than trusting the accessibility-tree reference.

Default to the cheap checks. Reach for a screenshot only when they disagree with each
other or with what you expect.

## When element references go stale

Long-running pages sometimes restore prior state faster than the next action can run —
a client-side router snapping the URL back to a previous session, or a reference captured
before a re-render pointing at the wrong element afterward.

If a located element stops responding (clicks land with no effect, or the wrong content
changes):

1. Take one screenshot to confirm the actual visual state
2. Fall back to a **raw coordinate click** at the visible control's position, bypassing
   the accessibility-tree reference entirely
3. Re-query the accessibility tree fresh before the next step, rather than reusing an
   older reference

This is a fallback, not the default — coordinate clicks break if the layout shifts.
Prefer accessibility-tree queries until they demonstrably fail.

## Rotating sessions

To start a clean session, navigate to the service's plain home URL rather than using an
in-page "new session" button. An in-page control that triggers a client-side route change
can redirect unpredictably — to a stale prior session, to an unrelated page — in a way a
full navigation does not.

```
navigate(home_url)
locate the prompt textbox on the fresh page
proceed with the next track's prompt
```

Do this every ~4 tracks, per [running the generator](05-running-the-generator.md#rotate-sessions-every-4-tracks).

## Batching

If the driving tool supports queuing multiple actions in one round trip (a click,
followed by a wait, followed by a text read), use it for sequences you can predict —
submitting a prompt and immediately waiting a fixed interval before the first status
check, for instance. Do not batch across a verification step: if step 4 above might need
a retry, that decision has to happen before the next action is chosen, not inside a
pre-committed batch.

## Harvesting the finished audio

Once every track is generated, don't download by clicking through each one manually.
Recover the audio URLs from the browser's network activity during playback instead —
see [`collect.js`](../tools/track-picker/collect.js) and the
[getting the audio](03-quality-screening.md#getting-the-audio) section, which document
the two failure modes this involves: autoplay contaminating the next track's URL, and a
play button's label flipping to "Pause" mid-scan.

## Putting it together

```
for each track prompt in the episode:
    if track_index % 4 == 0:
        navigate(generator_home_url)

    locate(prompt_textbox)                       # accessibility query
    set_value(prompt_textbox, full_prompt)

    locate(send_button)                           # accessibility query
    click(send_button)

    if not confirm_submitted():                   # text extraction
        screenshot()                               # fallback
        click(send_button, by_coordinate=True)     # fallback
        confirm_submitted()

    wait_for_generation()
    read_returned_title_and_tags()                 # text extraction
    record(prompted_title, returned_title, tags, take_count)

run collect.js in the tab
hand the resulting JSON to track-picker
```

This is the loop behind every episode in [`examples/`](../examples/) and the failure
modes in [song prompting](01-song-prompting.md#failure-modes) and
[running the generator](05-running-the-generator.md#failure-recovery).
