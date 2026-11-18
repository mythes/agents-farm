"""T3: the folder and model lists of the new-session dialog (logic only, no UI)."""

import os
from datetime import datetime, timedelta, timezone

from agents_farm import picker
from agents_farm.model import Agent

NOW = datetime.now(timezone.utc)


def agent(cwd="", model="", age=60, parent=""):
    a = Agent(id=f"{cwd}{model}{age}", transcript="", last_activity=NOW - timedelta(seconds=age))
    a.cwd, a.model, a.parent = cwd, model, parent
    return a


def tree(tmp_path):
    for name in ("api-refactor", "docs-writer", "lint-pass", ".hidden"):
        (tmp_path / name).mkdir(exist_ok=True)
    (tmp_path / "file.txt").write_text("x")
    return str(tmp_path)


def labels(rows):
    return [r.label for r in rows]


def test_split_path():
    assert picker.split_path("api") == (None, "api")
    assert picker.split_path("") == (None, "")
    assert picker.split_path("/a/b/") == ("/a/b", "")
    assert picker.split_path("/a/b/ap") == ("/a/b", "ap")
    assert picker.split_path("/ap") == ("/", "ap")
    assert picker.split_path("~") == (None, os.path.expanduser("~"))
    assert picker.split_path("~/x/")[0] == os.path.expanduser("~/x")


def test_a_folder_lists_its_subfolders_with_here_and_up_first(tmp_path):
    rows = picker.folder_rows(tree(tmp_path) + "/", [])
    assert [r.kind for r in rows[:2]] == ["here", "up"]
    assert rows[0].path == str(tmp_path) and rows[1].path == os.path.dirname(str(tmp_path))
    assert labels(rows[2:]) == ["api-refactor/", "docs-writer/", "lint-pass/"]     # no files, no hidden folders


def test_removing_the_last_name_shows_the_neighbours(tmp_path):
    base = tree(tmp_path)
    inside = picker.folder_rows(base + "/api-refactor/", [])
    assert inside[0].path == base + "/api-refactor" and labels(inside[2:]) == []
    parent = picker.folder_rows(base + "/", [])
    assert "docs-writer/" in labels(parent)


def test_fuzzy_matching_inside_a_folder_ranks_and_marks_letters(tmp_path):
    rows = picker.folder_rows(tree(tmp_path) + "/apirf", [])
    assert labels(rows)[0] == "api-refactor/" and "here" not in [r.kind for r in rows]
    assert rows[0].offsets and all(i < len("api-refactor") for i in rows[0].offsets)
    assert picker.folder_rows(tree(tmp_path) + "/zzz", []) == []


def test_hidden_folders_only_when_you_type_a_dot(tmp_path):
    base = tree(tmp_path)
    assert ".hidden/" not in labels(picker.folder_rows(base + "/", []))
    assert ".hidden/" in labels(picker.folder_rows(base + "/.h", []))


def test_no_slash_means_recent_projects(tmp_path):
    base = tree(tmp_path)
    recents = picker.recent_dirs([agent(base + "/api-refactor", age=30), agent(base + "/docs-writer", age=9000),
                                  agent(base + "/api-refactor", age=100), agent(base + "/gone", age=5), agent(base, parent="x")])
    assert [r.path for r in recents] == [base + "/api-refactor", base + "/docs-writer"]    # newest first, gone folder and subagent left out
    assert recents[0].sessions == 2
    rows = picker.folder_rows("", recents)
    assert [r.kind for r in rows] == ["recent", "recent"] and "2 sessions" in rows[0].meta
    hit = picker.folder_rows("docw", recents)
    assert [r.path for r in hit] == [base + "/docs-writer"] and hit[0].offsets


def test_unreadable_or_missing_folders_give_here_and_up(tmp_path):
    rows = picker.folder_rows(str(tmp_path / "nope") + "/", [])
    assert [r.kind for r in rows] == ["here", "up"]


def test_names_are_sanitised(tmp_path):
    (tmp_path / ("evil" + chr(0x202E) + "name")).mkdir()
    rows = picker.folder_rows(str(tmp_path) + "/", [])
    assert all(chr(0x202E) not in r.label for r in rows)


def test_descend_text(tmp_path):
    row = picker.Row("dir", "x/", str(tmp_path / "x"))
    assert picker.descend_text(row).endswith("/x/")


def test_git_branch_for_a_repo_a_worktree_and_a_plain_folder(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert picker.git_branch(str(plain)) == ""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/feature/x\n")
    assert picker.git_branch(str(repo)) == "feature/x"
    real = tmp_path / "real-git"
    real.mkdir()
    (real / "HEAD").write_text("0123456789abcdef\n")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {real}\n")
    assert picker.git_branch(str(wt)) == "01234567"


def test_preview_lists_folders_first_and_hides_dotfiles(tmp_path):
    base = tree(tmp_path)
    recents = [picker.Recent(base, 3, NOW - timedelta(hours=2))]
    lines = picker.preview(base, recents, NOW)
    assert lines[0] == ("bold", os.path.basename(base)) and "3 claude sessions · 2 h ago" in lines[1][1]
    names = [t for _, t in lines[3:]]
    assert names == ["api-refactor/", "docs-writer/", "lint-pass/", "file.txt"]
    assert picker.preview(str(tmp_path / "nope"), [])[-1][0] == "red"


def test_ago():
    assert picker.ago(NOW - timedelta(seconds=5), NOW) == "1 min ago"
    assert picker.ago(NOW - timedelta(hours=2), NOW) == "2 h ago"
    assert picker.ago(NOW - timedelta(days=5), NOW) == "5 d ago"
    assert picker.ago(None) == ""


# ------------------------------------------------------------------------------ models

def test_models_come_from_aliases_transcripts_and_config():
    agents = [agent(model="claude-sonnet-5-5", age=10), agent(model="claude-opus-5-5", age=900), agent(model="<synthetic>"),
              agent(model="claude-sonnet-5-5", age=5000), agent(model="--evil")]
    choices = picker.known_models(agents, ["my-model", "opus", 5, "bad model"], NOW)
    values = [c.value for c in choices]
    assert values == ["", "fable", "opus", "sonnet", "haiku", "claude-sonnet-5-5", "claude-opus-5-5", "my-model"]
    assert choices[0].label == "default" and "used 1 min ago" == choices[5].meta


def test_model_filter_is_fuzzy_and_offers_text_as_typed():
    choices = picker.known_models([agent(model="claude-opus-5-5")], [], NOW)
    hits = picker.filter_models(choices, "son")
    assert hits[0].value == "sonnet" and hits[0].offsets
    typed = picker.filter_models(choices, "zzz-model")
    assert typed[-1].value == "zzz-model" and "as typed" in typed[-1].label
    assert not any("as typed" in c.label for c in picker.filter_models(choices, "opus"))
    assert len(picker.filter_models(choices, "")) == len(choices)
