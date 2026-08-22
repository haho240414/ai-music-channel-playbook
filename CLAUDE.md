# CLAUDE.md

Read [`AGENTS.md`](AGENTS.md) — it holds the full instructions for working in this repo,
including the menu to greet the user with, the reading order per task, and the
non-negotiable rules.

Claude Code specifics:

- Slash commands are in `.claude/commands/` — `/new-episode`, `/song-prompts`,
  `/cover-prompts`, `/screen-tracks`
- When driving a music generator in the browser, follow
  [`docs/05-running-the-generator.md`](docs/05-running-the-generator.md) for the operating
  loop and [`docs/06-browser-automation.md`](docs/06-browser-automation.md) for the
  technique: query the accessibility tree before screenshotting, verify a send actually
  registered, fall back to a coordinate click if a reference goes stale, rotate sessions
  every ~4 tracks by navigating to the home URL, and record returned titles as you go
- You cannot hear audio. Do not imply otherwise when discussing track quality
