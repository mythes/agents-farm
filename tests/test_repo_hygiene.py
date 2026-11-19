"""Repository hygiene: keep the repo small, English-only and free of personal data."""

import os
import sys
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "agents_farm.egg-info", "node_modules"}
TEXT_EXT = {".py", ".md", ".toml", ".yml", ".yaml", ".sh", ".txt", ".json", ".cast", ""}

GIF_BUDGET = 350 * 1024           # one feature demo (the repo keeps every version of it forever)
GIF_TOTAL_BUDGET = 1536 * 1024    # all feature demos together
CAST_BUDGET = 1900 * 1024         # raw text of one cast; git stores it compressed
FILE_BUDGET = 2 * 1024 * 1024     # no other file may be bigger than this


def _files():
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            yield os.path.join(base, name)


def _text_files():
    for path in _files():
        if os.path.splitext(path)[1].lower() in TEXT_EXT and not path.endswith(".cast"):
            yield path


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _scenarios():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    try:
        import record_demo
        return list(record_demo.SCENARIOS)
    finally:
        sys.path.pop(0)


def test_demo_assets_stay_small():
    """One cast and one GIF per feature scenario, each small, and small together."""
    total = 0
    for name in _scenarios():
        for ext, budget in ((".gif", GIF_BUDGET), (".cast", CAST_BUDGET)):
            path = os.path.join(ROOT, "docs", "demo", name + ext)
            assert os.path.exists(path), f"docs/demo/{name}{ext} is missing: run scripts/make_demo.sh {name}"
            size = os.path.getsize(path)
            assert size <= budget, f"docs/demo/{name}{ext} is over its size budget ({size // 1024} KB)"
            total += size if ext == ".gif" else 0
    assert total <= GIF_TOTAL_BUDGET, f"the feature GIFs together are {total // 1024} KB: too big"


def test_every_feature_demo_is_shown_in_the_readme_and_every_link_works():
    readme = _read(os.path.join(ROOT, "README.md"))
    linked = set(re.findall(r"docs/demo/([a-z-]+)\.gif", readme))
    assert linked == set(_scenarios()), "the README must show each demo scenario once"
    for name in linked:
        assert os.path.exists(os.path.join(ROOT, "docs", "demo", name + ".gif"))


def test_the_rules_page_exists_and_the_readme_links_it():
    assert os.path.exists(os.path.join(ROOT, "docs", "rules.md"))
    assert "docs/rules.md" in _read(os.path.join(ROOT, "README.md"))


def test_no_large_files():
    for path in _files():
        assert os.path.getsize(path) <= FILE_BUDGET, f"{os.path.relpath(path, ROOT)} is larger than 2 MB"


def test_text_files_are_english_only():
    cyrillic = re.compile("[" + chr(0x0400) + "-" + chr(0x04FF) + "]")  # built with chr(): no literal Cyrillic in this file
    for path in _text_files():
        assert not cyrillic.search(_read(path)), f"non-English text in {os.path.relpath(path, ROOT)}"


def test_no_personal_data():
    # Built from parts so this file does not match itself.
    needles = ["olex" + "olex", "mythes" + "666", "@gm" + "ail.com", "/Users/" + "olex"]
    for path in _text_files():
        if path == os.path.abspath(__file__):
            continue
        text = _read(path)
        for needle in needles:
            assert needle not in text, f"personal data ({needle}) in {os.path.relpath(path, ROOT)}"


def test_version_is_consistent():
    pyproject = _read(os.path.join(ROOT, "pyproject.toml"))
    init = _read(os.path.join(ROOT, "agents_farm", "__init__.py"))
    a = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    b = re.search(r'__version__ = "([^"]+)"', init).group(1)
    assert a == b, f"pyproject has {a} but __init__ has {b}"


def test_every_skill_has_frontmatter():
    skills = os.path.join(ROOT, ".claude", "skills")
    for name in os.listdir(skills):
        text = _read(os.path.join(skills, name, "SKILL.md"))
        match = re.match(r"---\nname: (.+)\ndescription: (.+)\n(?:.*\n)*?---\n", text)
        assert match, f"{name}/SKILL.md needs a frontmatter with name and description"
        assert match.group(1).strip() == name, f"skill name must match its folder: {name}"


def test_actions_are_pinned_to_a_commit():
    """A tag can be moved by its owner. A full commit SHA cannot."""
    workflows = os.path.join(ROOT, ".github", "workflows")
    pinned = re.compile(r"@[0-9a-f]{40}(\s|$)")
    for name in os.listdir(workflows):
        for line in _read(os.path.join(workflows, name)).splitlines():
            match = re.match(r"\s*-?\s*uses:\s*(\S+)", line)
            if match and not match.group(1).startswith("./"):
                assert pinned.search(line), f"{name}: {match.group(1)} is not pinned to a commit SHA"


def test_workflows_declare_permissions():
    workflows = os.path.join(ROOT, ".github", "workflows")
    for name in os.listdir(workflows):
        assert re.search(r"^permissions:", _read(os.path.join(workflows, name)), re.M), f"{name} needs a top-level permissions block"
