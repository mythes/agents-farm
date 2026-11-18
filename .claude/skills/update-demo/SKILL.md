---
name: update-demo
description: Rebuild the README demo (docs/demo.cast and docs/demo.gif) after the UI changes, and keep it small. Use when keys, columns, layout or colours change, or when the demo data in demo.py changes.
---

# Update the demo

The demo has two files:

- `docs/demo.cast` is the **source**: a text recording (asciicast v2). Git stores it compressed (about 40 KB).
- `docs/demo.gif` is what the README shows. It must stay **under 1 MB** (it is about 350 KB now).

## Steps

1. Check the tools: `agg` and `gifsicle` (`brew install agg gifsicle` on macOS). Ask the user before you install anything.
2. If the keys or screens changed, edit the script in `scripts/record_demo.py` (`STEPS`). Each step is `(seconds to wait, bytes to send)`.
3. Run:

   ```bash
   scripts/make_demo.sh
   ```

   It records `agents-farm --demo` in a 120×30 terminal, builds the GIF, and fails if a size budget is broken.
4. Look at the result. Extract a few frames and read them:

   ```bash
   gifsicle -U docs/demo.gif '#30' -o /tmp/frame.gif
   ```

   Check that text is not cut, no frame is empty, and no real data is shown (the demo must use fake data only).
5. Run the `check` skill.

## Keep the repo small

- A new binary stays in git history forever. **Rebuild the GIF only when the UI changed in a way a viewer would see.** Do not rebuild it for a small code change.
- Commit the GIF and the cast together, in a commit that has a clear message.
- If the GIF is over budget, shorten the script (`STEPS`), lower `--fps-cap` or `--colors` in `scripts/make_demo.sh`, or both. Never commit video files (`.mp4`, `.webm`).
- The recording uses fake data (`--demo`) and a temporary config folder, so it never reads real sessions or the user config.

## Why GitHub cannot show an interactive player

A README cannot run scripts. So the README shows the GIF. People who want to explore can run `agents-farm --demo`, or play the recording with `asciinema play docs/demo.cast` (pause and seek work there).
