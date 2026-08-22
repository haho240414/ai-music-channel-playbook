---
description: Expand an episode brief into complete per-track song prompts
---

Read `docs/01-song-prompting.md` and `examples/02-song-prompts.md`.

Working from the episode brief (ask for it if you do not have one), write a prompt for
every track. Each must have all seven parts:

1. Title in quotes
2. BPM and key
3. Hook — instrument named, arrival in seconds
4. Texture — drums, bass, supporting instruments, production character
5. Scene — exactly one sentence
6. Negative list — voice terms, adjacent genres, production clichés
7. Length

Write the global prompt once and per-track lines separately, then show one fully
concatenated prompt so the user can see what gets submitted.

Verify before finishing:
- Every track names a hook instrument with a deadline in seconds
- The negative list names this genre's actual neighbours, not generic exclusions
- Only the designated tracks state the recurring motif
- No track subject contradicts the episode's season

$ARGUMENTS
