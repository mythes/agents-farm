---
name: update-demo
description: Rebuild the feature demos in docs/demo/ (one short cast and GIF per feature) after the UI changes, and keep them small. Use when keys, columns, layout or colours change, when a feature is added, or when the demo data in demo.py changes.
---

# Update the demos

There is one demo per feature. A scenario is a name in `scripts/record_demo.py` (`SCENARIOS`), and it makes two files:

- `docs/demo/NAME.cast` is the **source**: a text recording (asciicast v2). Git stores it compressed (about 30 to 60 KB).
- `docs/demo/NAME.gif` is what the README shows. It must stay **under 350 KB** (they are 70 to 200 KB now), and all GIFs together under 1.5 MB.

The README (Features section) shows each GIF once, with a short text. [docs/rules.md](../../../docs/rules.md) holds the exact rules.

## Steps

1. Check the tools: `agg` and `gifsicle` (`brew install agg gifsicle` on macOS). Ask the user before you install anything.
2. If keys or screens changed, edit the scenario in `scripts/record_demo.py`. A step is `(seconds to wait, bytes to send)`; `typed()` and `find()` build the common ones. For a new feature, add a scenario, a short section with its GIF to the README, and a line to `docs/rules.md`.
3. Rebuild only what changed (all of them take about two minutes):

   ```bash
   scripts/make_demo.sh resume      # one demo
   scripts/make_demo.sh             # all demos
   ```

   It records `agents-farm --demo` in a fake home folder, builds the GIF, and fails if a size budget is broken.
4. Look at the result. Extract a few frames and read them:

   ```bash
   gifsicle -U docs/demo/resume.gif '#12' -o /tmp/frame.gif
   ```

   Check that text is not cut, no frame is empty, no pop-up hides the keys, and no real data is shown (the demo must use fake data only). `grep -c "$USER\|/private/var" docs/demo/*.cast` must find nothing.
5. Run the `check` skill.

## Keep the repo small

- A new binary stays in git history forever. **Rebuild a GIF only when the UI of that feature changed in a way a viewer would see.** Do not rebuild it for a small code change.
- Commit the GIF and the cast together, in a commit with a clear message.
- If a GIF is over budget, shorten the scenario, lower `--fps-cap` or `--colors` in `scripts/make_demo.sh`, or both. Never commit video files (`.mp4`, `.webm`).
- The recording uses fake data (`--demo`), a fake home folder and a config with alerts off, so it never reads real sessions or the user config.

## Why GitHub cannot show an interactive player

A README cannot run scripts. So the README shows the GIFs. People who want to explore can run `agents-farm --demo`, or play a recording with `asciinema play docs/demo/resume.cast` (pause and seek work there).
