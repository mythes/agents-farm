---
name: release
description: Prepare and publish a new agents-farm release (version bump, changelog, tag, GitHub release). Use only when the user asks for a release.
disable-model-invocation: true
---

# Release

A release is public and cannot be undone cleanly. **Ask the user to confirm before you push, tag or publish.** Show what you will do first.

## Before you start

1. The working tree must be clean (`git status --short` is empty) and you are on `main`.
2. `git pull --ff-only` works, and the last CI run on `main` is green: `gh run list --branch main --limit 1`.
3. Run the `check` skill. All checks must pass.
4. Ask the user for the new version (semantic versioning: `0.x.y` while the API is not stable). Suggest one from the commits since the last tag (`git log <last-tag>..HEAD --oneline`).

## Steps

1. Update the version in **both** places: `pyproject.toml` (`version = "…"`) and `agents_farm/__init__.py` (`__version__`). A test checks they are equal.
2. Update `CHANGELOG.md` (create it if it does not exist). Use the sections **Added / Changed / Fixed / Security**, write plain English, one short line per change, and link issues like `#12`.
3. Run the `check` skill again.
4. Commit: `Release vX.Y.Z`.
5. **Ask for confirmation.** Then:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin main --follow-tags
   gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <notes>
   ```

   Use the changelog section of this version as the notes. Do not attach big files.
6. Check that the release page and the CI run are fine. Tell the user the release URL.

## Rules

- Never force-push and never move or delete an existing tag.
- The repository may be private. Do not change its visibility inside this skill.
- If a step fails, stop and report the real error. Do not retry with other flags to get around a check.
