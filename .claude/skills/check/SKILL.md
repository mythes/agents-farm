---
name: check
description: Run all agents-farm checks (tests, bandit, repo hygiene, whitespace) and fix what fails. Use before every commit, before a pull request, and after changing code, docs or demo files.
---

# Check the repository

Run:

```bash
scripts/check.sh
```

It runs `pytest` (security, context, repo hygiene), `bandit -r agents_farm` and `git diff --check`.

## If something fails

| Failure | What to do |
|---|---|
| `test_security.py` | Untrusted text reached the UI raw. Pass it through `sanitize()` (`model.py`). Never turn on markup for text from transcripts or hooks (`notify(..., markup=False)`, `rich.markup.escape` for titles). Do not weaken the test |
| `non-English text in …` | Docs, code, comments and demo data must be English. Rewrite the text in plain English (see the `docs-style` skill) |
| `personal data … in …` | Remove the user name, email or home path. Use placeholders such as `/Users/you` |
| `docs/demo.gif is over its size budget` | Run the `update-demo` skill. Do not raise the budget without a reason |
| `docs/demo.gif is missing` | Run `scripts/make_demo.sh` (needs `agg` and `gifsicle`) |
| `pyproject has X but __init__ has Y` | Make both versions the same |
| `…/SKILL.md needs a frontmatter` | Start the file with `---`, `name:` (same as the folder) and `description:` |
| bandit finding | Fix it. Use `# nosec B###` only for a reviewed, justified case and say why in a nearby comment |

## Rules

- Run the checks again after each fix until the output ends with `all checks passed`.
- Report the real output. If a check could not run (a missing tool), say so. Do not call the work done.
- Do not skip, delete or loosen a test to make it pass.
