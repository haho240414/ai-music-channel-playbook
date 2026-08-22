# CLAUDE.md

Read [`AGENTS.md`](AGENTS.md) — it holds the full instructions for working in this repo,
including the menu to greet the user with, the reading order per task, and the
non-negotiable rules.

Claude Code specifics:

- Slash commands are in `.claude/commands/` — `/new-episode`, `/song-prompts`,
  `/cover-prompts`, `/screen-tracks`
- When driving a music generator in the browser, follow
  [`docs/05-running-the-generator.md`](docs/05-running-the-generator.md): one prompt per
  message, confirm each submission actually registered, rotate sessions every ~4 tracks,
  and record returned titles as you go
- You cannot hear audio. Do not imply otherwise when discussing track quality
