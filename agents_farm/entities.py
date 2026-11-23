"""What Claude Code would find for a session in a folder: skills, plugins, MCP servers. No Textual imports.

Only files are read. Nothing is started, and no server is contacted. The folder can be one you do not trust, so every
file is checked (a regular file, limited size), every text is sanitised, and a broken file is skipped.

MCP settings can hold secrets. Only the kind and the program or host name are kept: never `env`, headers, arguments or
the path of a URL. Connectors of claude.ai and managed settings are not in these files, so the lists can be incomplete.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlsplit

from .model import sanitize

HEAD_BYTES = 16 * 1024              # of a SKILL.md: the front matter is at the top
JSON_BYTES = 8 * 1024 * 1024        # ~/.claude.json can be large
MAX_ENTRIES = 300                   # entries read from one folder
MAX_PARENTS = 30
NAME_LIMIT, NOTE_LIMIT = 60, 200


@dataclass
class Entity:
    name: str
    note: str = ""
    source: str = ""                # P project, L this project only for you, U you, C synced from claude.ai
    off: bool = False


@dataclass
class Entities:
    skills: List[Entity] = field(default_factory=list)
    plugins: List[Entity] = field(default_factory=list)
    mcp: List[Entity] = field(default_factory=list)
    also: List[str] = field(default_factory=list)


def roots() -> Tuple[str, str]:
    """(the Claude folder of the user, the file with the user's MCP servers)."""
    custom = os.environ.get("CLAUDE_CONFIG_DIR")
    home = os.path.expanduser("~")
    return (custom, os.path.join(custom, ".claude.json")) if custom else (os.path.join(home, ".claude"), os.path.join(home, ".claude.json"))


# ------------------------------------------------------------------------- reading files safely

def _read(path: str, limit: int, head: bool = False) -> Optional[str]:
    """The text of a regular file. Larger files give None, or their first bytes with `head`."""
    try:
        # O_NONBLOCK: a named pipe in the folder must not block us. The check is on the file that is really open.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except (OSError, ValueError):
        return None
    try:
        with os.fdopen(fd, "rb") as fh:
            info = os.fstat(fh.fileno())
            if not stat.S_ISREG(info.st_mode) or (info.st_size > limit and not head):
                return None
            return fh.read(limit).decode("utf-8", "replace")
    except OSError:
        return None


def _json(path: str) -> dict:
    try:
        data = json.loads(_read(path, JSON_BYTES) or "")
    except (ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _names(path: str) -> List[str]:
    names: List[str] = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if len(names) >= MAX_ENTRIES:
                    break
                if not entry.name.startswith("."):
                    names.append(entry.name)
    except (OSError, ValueError):
        return []
    return sorted(names, key=str.lower)


def _line(value, limit: int) -> str:
    """One clean line."""
    return " ".join(sanitize(value).split())[:limit] if isinstance(value, str) else ""


def front_matter(text: str) -> Dict[str, str]:
    """The top-level `key: value` pairs between the two `---` lines. A small part of YAML: plain, quoted and block texts."""
    lines = text.lstrip(chr(0xFEFF)).splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: Dict[str, str] = {}
    key = ""
    for line in lines[1:]:
        if line.strip() == "---":
            return {k: _unquote(v) for k, v in out.items()}
        if line[:1] in (" ", "\t"):
            if key:
                out[key] = (out[key] + " " + line.strip()).strip()
            continue
        key, colon, value = line.partition(":")
        key = key.strip() if colon else ""
        if key:
            value = value.strip()
            out[key] = "" if value in (">", "|", ">-", "|-", ">+", "|+") else value
    return {}                                   # no closing line: not front matter


def _unquote(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"" else value


# --------------------------------------------------------------------------------- the folders

def project_dirs(folder: str) -> List[str]:
    """The folder and its parents up to the root of the repository (only the folder itself outside a repository)."""
    folder = os.path.abspath(folder)
    dirs, here = [], folder
    for _ in range(MAX_PARENTS):
        dirs.append(here)
        if os.path.exists(os.path.join(here, ".git")):
            return dirs
        up = os.path.dirname(here)
        if up == here:
            break
        here = up
    return [folder]


def _skills(root: str, source: str) -> Iterator[Entity]:
    for name in _names(root):
        text = _read(os.path.join(root, name, "SKILL.md"), HEAD_BYTES, head=True)
        if text is not None:
            meta = front_matter(text)
            yield Entity(_line(meta.get("name"), NAME_LIMIT) or _line(name, NAME_LIMIT), _line(meta.get("description"), NOTE_LIMIT), source)


def _count_md(path: str) -> int:
    return sum(n.endswith(".md") for n in _names(path))


def _unique(found: List[Entity]) -> List[Entity]:
    """The first entity of each name and source, in the order found (nearest folder first)."""
    seen, out = set(), []
    for e in found:
        if (e.name, e.source) not in seen:
            seen.add((e.name, e.source))
            out.append(e)
    return out


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root)
    except (ValueError, OSError):
        return False


# --------------------------------------------------------------------------------- plugins, MCP

def _plugin(path: str, name: str, source: str, off: bool) -> Entity:
    manifest = _json(os.path.join(path, ".claude-plugin", "plugin.json")) if path else {}
    parts = []
    skills = sum(os.path.isfile(os.path.join(path, "skills", n, "SKILL.md")) for n in _names(os.path.join(path, "skills"))) if path else 0
    if skills:
        parts.append(f"{skills} skill{'s' if skills != 1 else ''}")
    servers = len(_dict(_json(os.path.join(path, ".mcp.json")).get("mcpServers"))) if path else 0
    if servers:
        parts.append(f"{servers} MCP")
    about = _line(manifest.get("description"), NOTE_LIMIT)
    return Entity(_line(name, NAME_LIMIT), " · ".join(([about] if about else []) + parts), source, off)


def _plugins(claude: str, dirs: List[str], settings: List[Tuple[str, dict]]) -> List[Entity]:
    enabled: Dict[str, Tuple[bool, str]] = {}
    for source, data in settings:                         # from the weakest to the strongest
        for pid, on in _dict(data.get("enabledPlugins")).items():
            if isinstance(on, bool):
                enabled[pid] = (on, source)
    root = os.path.join(claude, "plugins")
    found: Dict[str, Entity] = {}
    for pid, records in list(_dict(_json(os.path.join(root, "installed_plugins.json")).get("plugins")).items())[:MAX_ENTRIES]:
        for rec in records if isinstance(records, list) else []:
            rec = _dict(rec)
            project = rec.get("projectPath")
            if isinstance(project, str) and project and os.path.abspath(project) not in dirs:
                continue                                  # installed for another project
            path = rec.get("installPath")
            path = path if isinstance(path, str) and _inside(path, root) else ""
            on, _ = enabled.get(pid, (False, ""))
            found[pid] = _plugin(path, pid.split("@")[0], "P" if project else "U", not on)
            break
    for pid, (on, source) in list(enabled.items())[:MAX_ENTRIES]:
        if on and pid not in found:
            found[pid] = Entity(_line(pid.split("@")[0], NAME_LIMIT), "not installed here", source)
    for bucket in _names(os.path.join(root, "synced")):
        base = os.path.join(root, "synced", bucket)
        for name in _names(base):
            path = os.path.join(base, name)
            if os.path.isfile(os.path.join(path, ".claude-plugin", "plugin.json")):
                found[f"{name}@synced"] = _plugin(path, name, "C", not enabled.get(f"{name}@synced", (True, ""))[0])
    return sorted(found.values(), key=lambda e: (e.off, e.name.lower()))


def _server(name: str, conf, source: str, off: bool) -> Optional[Entity]:
    conf = _dict(conf)
    url, command = conf.get("url"), conf.get("command")
    if isinstance(url, str) and url:
        try:
            where = urlsplit(url).hostname or ""          # no user, password, path or query: they can hold a token
        except ValueError:
            where = ""
        kind = conf.get("type") if conf.get("type") in ("http", "sse", "ws") else "http"
    elif isinstance(command, str) and command.split():
        kind, where = "stdio", os.path.basename(command.split()[0])
    else:
        return None
    return Entity(_line(name, NAME_LIMIT), _line(f"{kind} · {where}" if where else kind, NOTE_LIMIT), source, off)


def _mcp(user_json: dict, dirs: List[str], settings: List[Tuple[str, dict]]) -> List[Entity]:
    rejected = {n for _, s in settings for n in (s.get("disabledMcpjsonServers") if isinstance(s.get("disabledMcpjsonServers"), list) else [])
                if isinstance(n, str)}
    sources: List[Tuple[str, dict]] = []
    projects = _dict(user_json.get("projects"))
    for d in dirs:
        sources.append(("L", _dict(_dict(projects.get(d)).get("mcpServers"))))
        sources.append(("P", _dict(_json(os.path.join(d, ".mcp.json")).get("mcpServers"))))
    sources.append(("U", _dict(user_json.get("mcpServers"))))
    found = [_server(n, c, src, src == "P" and n in rejected) for src, servers in sources for n, c in list(servers.items())[:MAX_ENTRIES]]
    return _unique([e for e in found if e])


# --------------------------------------------------------------------------------- all of it

def read(folder: str) -> Entities:
    claude, user_file = roots()
    dirs = project_dirs(folder)
    # The home folder is not a project: its .claude folder is the user's own.
    project = [d for d in dirs if os.path.realpath(os.path.join(d, ".claude")) != os.path.realpath(claude)]
    settings = [("U", _json(os.path.join(claude, "settings.json")))]
    for d in reversed(project):
        settings += [("P", _json(os.path.join(d, ".claude", "settings.json"))), ("L", _json(os.path.join(d, ".claude", "settings.local.json")))]

    out = Entities()
    skills: List[Entity] = []
    for d in project:
        skills += _skills(os.path.join(d, ".claude", "skills"), "P")
    skills += _skills(os.path.join(claude, "skills"), "U")
    for bucket in _names(os.path.join(claude, "skills", "synced")):
        skills += _skills(os.path.join(claude, "skills", "synced", bucket), "C")
    out.skills = _unique(skills)
    out.plugins = _plugins(claude, dirs, settings)
    out.mcp = _mcp(_json(user_file), dirs, settings)

    if any(os.path.isfile(os.path.join(d, *p)) for d in dirs for p in (("CLAUDE.md",), (".claude", "CLAUDE.md"))):
        out.also.append("CLAUDE.md")
    for kind in ("agents", "commands"):
        n = sum(_count_md(os.path.join(d, kind)) for d in [os.path.join(p, ".claude") for p in project] + [claude])
        if n:
            out.also.append(f"{n} {kind if n != 1 else kind[:-1]}")
    return out


def lines(e: Entities, height: int) -> List[Tuple[str, str, str, str]]:
    """(style, source letter, name, note) for the panel, at most `height` lines. Headings have no letter and no note.

    Every group keeps its heading with the full count. The room for items is shared: a short group gives its rest away.
    """
    groups = [("Skills", e.skills), ("Plugins", e.plugins), ("MCP servers", e.mcp)]
    gaps = height >= 22                                    # blank lines between the groups
    fixed = len(groups) * (2 if gaps else 1) + bool(e.also) + 1      # headings, "Also", the legend
    room = max(height - fixed, len(groups))
    take = [0] * len(groups)
    while room > 0 and any(t < len(g) for t, (_, g) in zip(take, groups)):
        for i, (_, g) in enumerate(groups):
            if room > 0 and take[i] < len(g):
                take[i] += 1
                room -= 1
    out: List[Tuple[str, str, str, str]] = []
    for n, (title, group) in zip(take, groups):
        out.append(("head", "", f"{title} ({len(group)})", ""))
        left = len(group) - n
        if left and n > 1:
            n, left = n - 1, left + 1                      # the last line says how many are hidden
        out += [("off" if x.off else "item", x.source, x.name, ("off · " if x.off else "") + x.note if x.note or x.off else "") for x in group[:n]]
        if left:
            out.append(("more", "", f"+{left} more", ""))
        if gaps:
            out.append(("", "", "", ""))
    if e.also:
        out += [("more", "", "Also: " + " · ".join(e.also), "")]
    out.append(("more", "", "P project · L local · U you · C claude.ai", ""))
    return out
