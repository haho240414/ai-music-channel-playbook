/* Collect track audio URLs from a web music generator's session, in one pass.
 *
 * Usage: paste into the browser console on the generator's session tab. Save the
 * returned JSON as tracks.json, then:
 *     python3 run.py --urls tracks.json --out ./ep06 --episode "Episode Name"
 *
 * How it works: the player does not expose an <audio> element in the DOM, but playing a
 * track does fetch its audio file. Clicking each play button and reading the Performance
 * Resource Timing entries recovers the URLs without a manual download per track.
 *
 * Adapting to another generator: edit the CFG block below, or override it without
 * touching this file:
 *
 *     window.__pickConfig = {
 *       clipPattern: /audio\/[\w-]+\.mp3/,
 *       playLabel: /^play track/i,
 *       titleFrom: (l) => l.replace(/^play track:\s+/i, "").trim(),
 *     };
 *     // ...then paste this script.
 *
 * If a long episode times out, run it in slices via window.__pickStart / __pickCount.
 */
(async () => {
  // ---------------------------------------------------------------- config
  // Everything service-specific lives here. Adapting to another generator should
  // only require editing this block. Override any of it before running by setting
  // window.__pickConfig = { ... }.
  const CFG = Object.assign({
    // URL pattern of the audio files the player fetches.
    clipPattern: /clips\/[\w-]+\.m4a/,
    // How a track's play button is labelled, and how to get the title from it.
    playLabel: /^Play /,
    titleFrom: (label) => label.replace(/^Play\s+/, "").trim(),
    // Transport controls that share the play-button label but are not tracks.
    transportLabel: /^Play (previous|next)\b/i,
    // How a playing track's button is labelled, used to stop playback.
    pauseLabel: /^Pause /,
    // Milliseconds to wait after a click for the audio request to land.
    waitMs: 2200,
    // Slice of the button list to process (for very long episodes).
    start: 0,
    count: 999,
  }, window.__pickConfig || {});

  const START = window.__pickStart ?? CFG.start;
  const COUNT = window.__pickCount ?? CFG.count;
  const WAIT_MS = CFG.waitMs;
  const CLIP_RE = CFG.clipPattern;

  // Do NOT extract BPM by proximity. Searching around the title picks up the PREVIOUS
  // track's BPM and shifts every value by one position (this bug happened twice).
  // Embedding the title in the regex targets both prompt word orders exactly:
  //   A) '... titled "Title," 100 BPM'
  //   B) '... at 96 BPM titled "Title"'
  // Failing both, fall back to the tag line that follows the title on the track card.
  const bpmForTitle = (title) => {
    const txt = document.body.innerText || "";
    const esc = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

    let m = txt.match(new RegExp(esc + '[",.]*\\s*,?\\s*(\\d{2,3})\\s*BPM', "i"));
    if (m) return parseInt(m[1], 10);

    m = txt.match(new RegExp('(\\d{2,3})\\s*BPM[^.]{0,60}?titled\\s*"?' + esc, "i"));
    if (m) return parseInt(m[1], 10);

    const last = txt.lastIndexOf(title);
    if (last >= 0) {
      m = txt.slice(last, last + 300).match(/(\d{2,3})\s*bpm/i);
      if (m) return parseInt(m[1], 10);
    }
    return null;
  };

  // The player bar's previous/next buttons are also labelled "Play ...", so they get
  // mistaken for tracks. Capture each title NOW: a button's label flips to "Pause ..."
  // while it plays, and reading it later inside the loop records "Pause <title>" as the
  // track name (this bug happened).
  const buttons = Array.from(document.querySelectorAll("button"))
    .filter((b) => {
      const l = b.getAttribute("aria-label") || "";
      return CFG.playLabel.test(l) && !CFG.transportLabel.test(l);
    })
    .map((b) => ({ el: b, title: CFG.titleFrom(b.getAttribute("aria-label") || "") }));

  // The generator's own tag line for the track. If it omits "instrumental", vocals may
  // have been added despite the prompt -- disqualifying on an instrumental channel.
  //
  // A title appears several times on the page (in the prompt, on the card, in the
  // assistant's reply). The tag line is the one that ENDS with ", 100 bpm" -- prose
  // reads "at 100 BPM." instead -- so scan occurrences until one matches that shape.
  const tagsForTitle = (title) => {
    const txt = document.body.innerText || "";
    let from = 0;
    let idx;
    while ((idx = txt.indexOf(title, from)) >= 0) {
      const after = txt.slice(idx + title.length, idx + title.length + 400);
      const line = after.split("\n").map((s) => s.trim()).filter(Boolean)[0];
      if (line && /,\s*\d{2,3}\s*bpm$/i.test(line)) return line;
      from = idx + title.length;
    }
    return null;
  };

  const pauseAll = () => {
    Array.from(document.querySelectorAll("button"))
      .filter((b) => CFG.pauseLabel.test(b.getAttribute("aria-label") || ""))
      .forEach((b) => b.click());
  };

  const slice = buttons.slice(START, START + COUNT);
  const byTitle = new Map();

  for (let i = 0; i < slice.length; i++) {
    const { el: btn, title } = slice[i];

    try {
      // Stop whatever is playing first. When a track ends the player auto-advances and
      // fetches the next file, whose URL then gets attributed to the wrong track (this
      // bug happened).
      pauseAll();
      await new Promise((r) => setTimeout(r, 300));

      performance.clearResourceTimings();
      const t0 = performance.now();
      btn.click();
      await new Promise((r) => setTimeout(r, WAIT_MS));

      // Accept only the FIRST clip requested after the click as belonging to this track.
      const hit = performance
        .getEntriesByType("resource")
        .filter((r) => CLIP_RE.test(r.name) && r.startTime >= t0)
        .sort((a, b) => a.startTime - b.startTime)[0];

      pauseAll();
      await new Promise((r) => setTimeout(r, 250));

      if (!byTitle.has(title)) {
        byTitle.set(title, {
          title,
          target_bpm: bpmForTitle(title),
          tags: tagsForTitle(title),
          urls: [],
        });
      }
      const rec = byTitle.get(title);
      if (hit && !rec.urls.includes(hit.name)) rec.urls.push(hit.name);
    } catch (e) {
      console.warn("collect failed for", title, e);
    }
  }

  const out = Array.from(byTitle.values());
  console.log(JSON.stringify(out, null, 2));
  return {
    buttons_total: buttons.length,
    collected: out.length,
    missing: out.filter((o) => !o.urls.length).map((o) => o.title),
    data: out,
  };
})();
