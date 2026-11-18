"""Logic for the new-session dialog (T3): which folders and which models to offer. No Textual imports.

Folders work like a small file browser:
    "~/work/"     -> the sub-folders of ~/work (first: ".." and "use this folder")
    "~/work/ap"   -> the sub-folders of ~/work that match "ap" (fuzzy), best first
    "api"         -> no "/" in the text: your recent projects that match "api"
    ""            -> all recent projects, newest first
Only folder names are listed. Nothing is read recursively, and every name is sanitised.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from textual.fuzzy import FuzzySearch

from .model import Agent, sanitize

LIST_LIMIT = 500          # entries read from one folder
PREVIEW_LIMIT = 40        # entries shown in the preview
ALIASES = ("fable", "opus", "sonnet", "haiku")   # Claude Code resolves these to the latest model


@dataclass
class Row:
    kind: str                         # here | up | dir | recent
    label: str                        # what is shown
    path: str                         # the folder this row stands for (absolute)
    offsets: List[int] = field(default_factory=list)   # matched letters in `label`
    meta: str = ""                    # small grey text on the right


@dataclass
class Recent:
    path: str
    sessions: int
    last: Optional[datetime]


def tidy(path: str) -> str:
    """Show the home folder as ~."""
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


def ago(then: Optional[datetime], now: Optional[datetime] = None) -> str:
    if not then:
        return ""
    now = now or datetime.now(then.tzinfo)
    s = int(max((now - then).total_seconds(), 0))
    for limit, unit, size in ((3600, "min", 60), (48 * 3600, "h", 3600)):
        if s < limit:
            return f"{max(s // size, 1)} {unit} ago"
    return f"{s // 86400} d ago"


# ----------------------------------------------------------------------------- folders

def recent_dirs(agents: Iterable[Agent]) -> List[Recent]:
    """Folders of the sessions we know, newest first. Folders that are gone are left out."""
    found: Dict[str, Recent] = {}
    for a in agents:
        if not a.cwd or a.parent or not os.path.isdir(a.cwd):
            continue
        r = found.setdefault(a.cwd, Recent(a.cwd, 0, None))
        r.sessions += 1
        if a.last_activity and (r.last is None or a.last_activity > r.last):
            r.last = a.last_activity
    return sorted(found.values(), key=lambda r: r.last.timestamp() if r.last else 0, reverse=True)


def list_subdirs(path: str, show_hidden: bool = False, limit: int = LIST_LIMIT) -> List[str]:
    """Names of the sub-folders (links to folders too), sorted. Errors give an empty list."""
    names: List[str] = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if len(names) >= limit:
                    break
                if not show_hidden and entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir():          # follows links, so a link to a folder counts
                        names.append(entry.name)
                except OSError:
                    continue
    except OSError:
        return []
    return sorted(names, key=str.lower)


def split_path(text: str) -> Tuple[Optional[str], str]:
    """(folder to list, fragment to match). The folder is None when the text has no '/'."""
    text = text or ""
    if text == "~":
        return None, os.path.expanduser(text)
    text = os.path.expanduser(text)
    if "/" not in text:
        return None, text
    base, _, fragment = text.rpartition("/")
    return (base or "/"), fragment


def folder_rows(text: str, recents: Sequence[Recent], now: Optional[datetime] = None) -> List[Row]:
    """The list under the path field."""
    base, fragment = split_path(text)
    fuzzy = FuzzySearch(case_sensitive=False)
    if base is None:
        rows = []
        for r in recents:
            label = tidy(r.path)
            score, offsets = fuzzy.match(fragment, label) if fragment else (1.0, [])
            if score > 0:
                meta = f"{r.sessions} session{'s' if r.sessions != 1 else ''} · {ago(r.last, now)}".rstrip(" ·")
                rows.append((score, Row("recent", label, r.path, list(offsets), meta)))
        if fragment:
            rows.sort(key=lambda x: -x[0])
        return [r for _, r in rows]
    full = os.path.abspath(base)
    rows: List[Row] = []
    if not fragment:
        rows.append(Row("here", "use this folder", full))
        if full != os.path.dirname(full):
            rows.append(Row("up", "..", os.path.dirname(full)))
    scored: List[Tuple[float, Row]] = []
    for name in list_subdirs(full, show_hidden=fragment.startswith(".")):
        label = sanitize(name)
        score, offsets = fuzzy.match(fragment, label) if fragment else (1.0, [])
        if score > 0:
            scored.append((score, Row("dir", label + "/", os.path.join(full, name), [i for i in offsets if i < len(label)])))
    if fragment:
        scored.sort(key=lambda x: -x[0])
    return rows + [r for _, r in scored]


def descend_text(row: Row) -> str:
    """The text for the path field after Tab or → on a row: go into that folder."""
    return tidy(row.path).rstrip("/") + "/"


def git_branch(path: str) -> str:
    """The current branch, read from .git/HEAD (no git command). '' if it is not a repository."""
    dot = os.path.join(path, ".git")
    try:
        if os.path.isfile(dot):                      # a worktree: ".git" is a file that points to the real folder
            with open(dot, encoding="utf-8", errors="replace") as fh:
                line = fh.read(1000).strip()
            if not line.startswith("gitdir:"):
                return ""
            gitdir = line[7:].strip()
            dot = gitdir if os.path.isabs(gitdir) else os.path.join(path, gitdir)
        with open(os.path.join(dot, "HEAD"), encoding="utf-8", errors="replace") as fh:
            head = fh.read(300).strip()
    except OSError:
        return ""
    if head.startswith("ref: refs/heads/"):
        return sanitize(head[16:])[:60]
    return sanitize(head[:8]) if head else ""


def preview(path: str, recents: Sequence[Recent], now: Optional[datetime] = None) -> List[Tuple[str, str]]:
    """Lines for the preview panel: (style, text)."""
    out: List[Tuple[str, str]] = [("bold", sanitize(os.path.basename(path.rstrip("/")) or "/"))]
    branch = git_branch(path)
    info = [f"⎇ {branch}"] if branch else []
    known = next((r for r in recents if r.path == path), None)
    if known:
        info.append(f"{known.sessions} claude session{'s' if known.sessions != 1 else ''} · {ago(known.last, now)}")
    out.append(("grey70", "   ".join(info) if info else "no claude sessions seen here"))
    out.append(("", ""))
    try:
        with os.scandir(path) as it:
            entries = []
            for e in it:
                if len(entries) >= LIST_LIMIT:
                    break
                if e.name.startswith("."):
                    continue
                try:
                    entries.append((not e.is_dir(), e.name.lower(), sanitize(e.name), e.is_dir()))
                except OSError:
                    continue
    except OSError as exc:
        return out + [("red", f"cannot read this folder ({exc.strerror or 'error'})")]
    entries.sort()
    if not entries:
        return out + [("grey50", "(empty)")]
    for _, _, name, is_dir in entries[:PREVIEW_LIMIT]:
        out.append(("cyan", name + "/") if is_dir else ("grey70", name))
    if len(entries) > PREVIEW_LIMIT:
        out.append(("grey50", f"… and {len(entries) - PREVIEW_LIMIT} more"))
    return out


# ------------------------------------------------------------------------------ models

@dataclass
class ModelChoice:
    value: str          # "" = Claude's default (no --model)
    label: str
    meta: str = ""
    offsets: List[int] = field(default_factory=list)


def known_models(agents: Iterable[Agent], extra: Optional[Sequence[str]] = None, now: Optional[datetime] = None) -> List[ModelChoice]:
    """default, the aliases, models seen in transcripts (newest first), then models from the config."""
    from .runner import check_model, RunError

    def valid(name: str) -> bool:
        try:
            return bool(check_model(name))
        except RunError:
            return False

    choices = [ModelChoice("", "default", "Claude's own default")]
    choices += [ModelChoice(a, a, "alias: always the latest version") for a in ALIASES]
    seen = {c.value for c in choices}
    last: Dict[str, Tuple[int, Optional[datetime]]] = {}
    for a in agents:
        if a.model and valid(a.model):
            n, t = last.get(a.model, (0, None))
            last[a.model] = (n + 1, a.last_activity if a.last_activity and (t is None or a.last_activity > t) else t)
    for name, (n, t) in sorted(last.items(), key=lambda kv: kv[1][1].timestamp() if kv[1][1] else 0, reverse=True):
        if name not in seen:
            seen.add(name)
            choices.append(ModelChoice(name, name, f"used {ago(t, now)}".strip()))
    for name in extra or []:
        if isinstance(name, str) and name not in seen and valid(name):
            seen.add(name)
            choices.append(ModelChoice(name, name, "from your config"))
    return choices


def filter_models(choices: Sequence[ModelChoice], text: str) -> List[ModelChoice]:
    """Fuzzy filter. If the text is not in the list, the last row offers it 'as typed'."""
    text = (text or "").strip()
    if not text:
        return list(choices)
    fuzzy = FuzzySearch(case_sensitive=False)
    hits: List[Tuple[float, ModelChoice]] = []
    for c in choices:
        score, offsets = fuzzy.match(text, c.label)
        if score > 0:
            hits.append((score, ModelChoice(c.value, c.label, c.meta, list(offsets))))
    hits.sort(key=lambda x: -x[0])
    out = [c for _, c in hits]
    if not any(c.value == text for c in choices):
        out.append(ModelChoice(text, f'use "{sanitize(text)[:60]}" as typed', ""))
    return out
