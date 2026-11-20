---
name: release
description: Prepare and publish a new agents-farm release (version bump, changelog, README, demos, tag, GitHub release, Homebrew). Use only when the user asks for a release.
disable-model-invocation: true
---

# Release

A release is public and cannot be undone cleanly. **Ask the user to confirm before you push, tag or publish** (the tap too). Show what you will do first. Do the steps in this order: each one needs the one before it.

## Checklist

Copy this list into the task list and tick it off while you work.

**A. Prepare (local only, nothing is public yet)**

- [ ] 1. The working tree is clean or holds only this release's work (`git status --short`), you are on `main`, `git pull --ff-only` works, and the last CI run on `main` is green (`gh run list --branch main --limit 1`)
- [ ] 2. Choose the version with the user (`0.x.y`; suggest one from `git log <last-tag>..HEAD --oneline`: fix = patch, new feature = minor)
- [ ] 3. Review the backlog: `docs/backlog.md` and the GitHub issues match what was built (run the `sync-backlog` skill)
- [ ] 4. Update the **README** and `docs/` for what changed: new keys, columns, features, install steps, the help text (`helptext.py`) and `docs/rules.md` (run the `docs-style` skill on every text you write)
- [ ] 5. Rebuild the **demos** only if the UI changed in a visible way (run the `update-demo` skill)
- [ ] 6. Run the `perf-check` skill when code that runs on every refresh changed (app, store, registry, render, events)
- [ ] 7. Bump the version in **both** `pyproject.toml` and `agents_farm/__init__.py` (a test checks they are equal)
- [ ] 8. Update `CHANGELOG.md` with the sections **Added / Changed / Fixed / Security**: plain English, one short line per change, issues as `#12`. Move `[Unreleased]` items under the new version and date
- [ ] 9. Run the `check` skill: it must end with `all checks passed`
- [ ] 10. Commit: `Release vX.Y.Z`

**B. Publish (ask first)**

- [ ] 11. **Ask for confirmation**, then push and create the **tag**:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin main --follow-tags
   ```

- [ ] 12. Create the **GitHub release** with the changelog section as notes (no big files):

   ```bash
   awk '/^## \[X.Y.Z\]/{f=1;next}/^## \[PREVIOUS\]/{f=0}f' CHANGELOG.md > /tmp/notes.md
   gh release create vX.Y.Z --title "vX.Y.Z" --notes-file /tmp/notes.md
   ```

- [ ] 13. Check the release page and the CI run. Tell the user the release URL

**C. Homebrew (separate repository `mythes/homebrew-tap`)**

- [ ] 14. In `$(brew --repository mythes/tap)/Formula/agents-farm.rb` set the new tag in `url` and the new `sha256` (`curl -sL <url> | shasum -a 256`). If the dependencies changed, refresh the `resource` blocks (`brew update-python-resources mythes/tap/agents-farm`)
- [ ] 15. Test: `brew reinstall mythes/tap/agents-farm`, `brew test mythes/tap/agents-farm`, `brew audit --strict --online mythes/tap/agents-farm`
- [ ] 16. **Ask the user**, then commit and push the tap (`Update agents-farm to vX.Y.Z`)

**D. After**

- [ ] 17. Tell the user how to update: `brew upgrade agents-farm`. If `af --version` still shows the old version, another `af` comes first in `PATH` (a local link from `scripts/install.sh`): run it again or use the full path from the Cellar
- [ ] 18. Mark the finished tasks in the backlog and close their issues

## Rules

- Never force-push and never move or delete an existing tag.
- The repository may be private. Do not change its visibility inside this skill.
- Do not change the git identity. Commits use the GitHub noreply email from the local git config.
- If a step fails, stop and report the real error. Do not retry with other flags to get around a check.
- Never skip a step silently. If you skip one (for example, the demos did not change), say so in the final report.
