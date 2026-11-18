"""Textual dashboard — layout "A": agents list | details, limits bar at the bottom."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess  # nosec B404
import tempfile
from typing import Dict, List, Optional, Set, Tuple

from rich.console import Console
from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Collapsible, DataTable, Footer, Input, Static

from .model import STATUS_ORDER, Agent, Snapshot, Status
from . import killer, picker, runner
from . import render as R
from .search import Query

NARROW_WIDTH = 112   # below this width we show one panel (list or details)

HELP = [
    ("↑↓ / j k", "move between agents"),
    ("enter / z", "zoom: details full screen (esc to go back)"),
    ("1 2 3", "toggle Context / Activity / Plan"),
    ("e", "expand or collapse all sections"),
    ("/", "search: type letters (apirf finds api-refactor); filters: status:waiting model:opus project:api"),
    ("h", "show / hide idle sessions and finished subagents"),
    ("y", "copy `claude --resume` command for the agent"),
    ("p", "copy the PID of the agent's process"),
    ("x", "stop the agent's process (asks first; the default answer is No)"),
    ("n", "new `claude` session in this terminal: pick a folder, then ctrl+a model, ctrl+s mode, ctrl+d worktree"),
    ("o", "open the agent's full log in $PAGER"),
    ("r", "refresh now"),
    ("?", "this help"),
    ("q", "quit"),
]


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,q,question_mark", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        t = Text()
        t.append("agents-farm — keys\n\n", style="bold")
        for key, desc in HELP:
            t.append(f"  {key:<12}", style="bold cyan")
            t.append(desc + "\n")
        t.append("\nStatus  ", style="bold")
        for st in Status:
            sym, style = R.STATUS_STYLE[st]
            t.append(f" {sym} ", style=style)
            t.append(f" {st.value}  ")
        t.append("\n\nesc to close", style="grey50")
        yield Static(t, id="help-body")

    def on_click(self) -> None:
        self.dismiss()


class ConfirmKill(ModalScreen[bool]):
    """Asks before a signal is sent. Only `y` confirms: Enter, n and Esc all cancel."""

    BINDINGS = [Binding("y", "confirm", "Yes"), Binding("n,escape,enter", "cancel", "No")]

    def __init__(self, question: str, details: List[Tuple[str, str]], yes_label: str):
        super().__init__()
        self._question, self._details, self._yes_label = question, details, yes_label

    def compose(self) -> ComposeResult:
        t = Text()
        t.append(self._question + "\n\n", style="bold")
        for style, line in self._details:
            t.append(line + "\n", style=style)
        t.append("\n  y ", style="bold black on red")
        t.append(f" {self._yes_label}      ")
        t.append(" n ", style="bold black on green")
        t.append(" cancel (also Esc or Enter)", style="")
        yield Static(t, id="kill-body")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


def _list_cell(label: str, offsets: List[int], style: str = "") -> Text:
    t = Text(label, style=style)
    for i in offsets:
        if i < len(label):
            t.stylize(R.MATCH_STYLE, i, i + 1)
    return t


class ModelPicker(ModalScreen):
    """Pick a model from a short fuzzy list. Dismisses with the model ('' = default) or None."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("up", "move(-1)", "Up", show=False, priority=True),
        Binding("down", "move(1)", "Down", show=False, priority=True),
    ]

    def __init__(self, choices: List[picker.ModelChoice], current: str):
        super().__init__()
        self._choices, self._current = choices, current
        self._shown: List[picker.ModelChoice] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="mp-body"):
            yield Input(placeholder="type to filter, or a model name", id="mp-filter", compact=True)
            yield DataTable(id="mp-list", cursor_type="row", show_header=False, zebra_stripes=False)
            yield Static("", id="mp-error")
            yield Footer()

    def on_mount(self) -> None:
        body = self.query_one("#mp-body")
        body.border_title = "MODEL"
        body.border_subtitle = "enter: use the marked model"
        table = self.query_one("#mp-list", DataTable)
        table.can_focus = False
        table.add_column("name", key="name")
        table.add_column("meta", key="meta")
        self._fill("")
        self.query_one("#mp-filter", Input).focus()

    def _fill(self, text: str) -> None:
        table = self.query_one("#mp-list", DataTable)
        table.clear()
        self._shown = picker.filter_models(self._choices, text)
        for i, c in enumerate(self._shown):
            mark = "● " if c.value == self._current else "  "
            table.add_row(_list_cell(mark + c.label, [o + 2 for o in c.offsets], "bold" if c.value == self._current else ""),
                          Text(c.meta, style="grey58"), key=str(i))
        self.query_one("#mp-error", Static).update("")

    @on(Input.Changed)
    def _changed(self, event: Input.Changed) -> None:
        self._fill(event.value)

    def action_move(self, step: int) -> None:
        table = self.query_one("#mp-list", DataTable)
        table.action_cursor_down() if step > 0 else table.action_cursor_up()

    @on(Input.Submitted)
    def _pick(self) -> None:
        row = self.query_one("#mp-list", DataTable).cursor_row
        if not 0 <= row < len(self._shown):
            return
        value = self._shown[row].value
        try:
            runner.check_model(value)
        except runner.RunError as exc:
            self.query_one("#mp-error", Static).update(Text(str(exc), style="bold red"))
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class NewSession(ModalScreen):
    """Where and how to start `claude`. Dismisses with a dict, or None when cancelled.

    The folder list works like a small file browser (see picker.py). Nothing starts until
    Enter, and the folder is checked again before it closes.
    """

    BINDINGS = [
        Binding("up", "move(-1)", "Up", show=False, priority=True),
        Binding("down", "move(1)", "Down", show=False, priority=True),
        Binding("tab", "descend", "Open folder", priority=True),
        Binding("right", "descend_right", "Open", show=False, priority=True),
        Binding("enter", "start", "Start", show=True),
        Binding("ctrl+a", "model", "Model", priority=True),
        Binding("ctrl+s", "mode", "Mode", priority=True),
        Binding("ctrl+d", "worktree", "Worktree", priority=True),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, cwd: str, agents: List[Agent], opts: Dict, extra_models: List[str]):
        super().__init__()
        self._cwd = cwd
        self._agents, self._extra = agents, extra_models
        self._recents = picker.recent_dirs(agents)
        self.opts = dict(opts)
        self._rows: List[picker.Row] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="new-body"):
            yield Input(picker.tidy(self._cwd).rstrip("/") + "/", id="ns-dir", compact=True)
            with Horizontal(id="ns-main"):
                yield DataTable(id="ns-list", cursor_type="row", show_header=False, zebra_stripes=False)
                yield Static(id="ns-preview")
            yield Static(id="ns-opts")
            yield Static(id="ns-error")
            yield Static(self._hints(), id="ns-hints")

    def on_mount(self) -> None:
        self.query_one("#new-body").border_title = "NEW SESSION"
        self.query_one("#new-body").border_subtitle = "enter: start in the marked folder"
        table = self.query_one("#ns-list", DataTable)
        table.can_focus = False
        table.add_column("name", key="name")
        table.add_column("meta", key="meta")
        self.query_one("#ns-preview").border_title = "PREVIEW"
        field = self.query_one("#ns-dir", Input)
        field.focus()
        field.action_end()
        self._fill(field.value)
        self._show_opts()
        self._apply_size(self.size.width)

    @staticmethod
    def _hints() -> Text:
        """Like the footer, but in a fixed order (the real footer orders keys by how Textual finds them)."""
        t = Text(no_wrap=True, overflow="ellipsis")
        for key, label in (("tab", "Open folder"), ("^a", "Model"), ("^s", "Mode"), ("^d", "Worktree"), ("esc", "Cancel")):
            t.append(f" {key} ", style="bold #ffaf00")
            t.append(f"{label} ")
        return t

    def on_resize(self, event) -> None:
        self._apply_size(event.size.width)

    def _apply_size(self, width: int) -> None:
        self.query_one("#new-body").set_class(width < 100, "-narrow")

    # ----------------------------------------------------------------- list

    def _fill(self, text: str) -> None:
        table = self.query_one("#ns-list", DataTable)
        table.clear()
        self._rows = picker.folder_rows(text, self._recents)
        for i, r in enumerate(self._rows):
            style = {"here": "bold green", "up": "grey70"}.get(r.kind, "")
            label = ("● " if r.kind == "here" else "") + r.label
            table.add_row(_list_cell(label, [o + (2 if r.kind == "here" else 0) for o in r.offsets], style),
                          Text(r.meta, style="grey58"), key=str(i))
        base, fragment = picker.split_path(text)
        table.border_title = ("RECENT PROJECTS" if base is None else "FOLDERS") + f" ({len(self._rows)})"
        self.query_one("#ns-error", Static).update("")
        self._show_preview()

    def _current(self) -> Optional[picker.Row]:
        row = self.query_one("#ns-list", DataTable).cursor_row
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _show_preview(self) -> None:
        row = self._current()
        t = Text()
        if row:
            for style, line in picker.preview(row.path, self._recents):
                t.append(line + "\n", style=style)
        else:
            t.append("nothing matches", style="grey50")
        self.query_one("#ns-preview", Static).update(t)

    @on(Input.Changed, "#ns-dir")
    def _changed(self, event: Input.Changed) -> None:
        self._fill(event.value)

    @on(DataTable.RowHighlighted, "#ns-list")
    def _moved(self) -> None:
        self._show_preview()

    def action_move(self, step: int) -> None:
        table = self.query_one("#ns-list", DataTable)
        table.action_cursor_down() if step > 0 else table.action_cursor_up()

    def check_action(self, action: str, parameters) -> Optional[bool]:
        # → opens a folder only when the text cursor is at the end. Otherwise it moves the cursor as usual.
        if action == "descend_right":
            field = self.query_one("#ns-dir", Input)
            return field.cursor_position >= len(field.value)
        return True

    def action_descend_right(self) -> None:
        self.action_descend()

    def action_descend(self) -> None:
        row = self._current()
        if row and row.kind != "here":
            field = self.query_one("#ns-dir", Input)
            field.value = picker.descend_text(row)
            field.action_end()

    # ------------------------------------------------------------- options

    def _show_opts(self) -> None:
        o = self.opts
        t = Text()
        t.append(" model ", style="grey58")
        t.append(o["model"] or "default", style="bold")
        t.append("   mode ", style="grey58")
        t.append(o["mode"], style="bold")
        t.append("   worktree ", style="grey58")
        t.append("on" if o["worktree"] else "off", style="bold green" if o["worktree"] else "bold")
        self.query_one("#ns-opts", Static).update(t)

    def action_model(self) -> None:
        choices = picker.known_models(self._agents, self._extra)
        self.app.push_screen(ModelPicker(choices, self.opts["model"]), self._model_chosen)

    def _model_chosen(self, value) -> None:
        if value is not None:
            self.opts["model"] = value
            self._show_opts()

    def action_mode(self) -> None:
        modes = runner.PERMISSION_MODES
        self.opts["mode"] = modes[(modes.index(self.opts["mode"]) + 1) % len(modes)]
        self._show_opts()

    def action_worktree(self) -> None:
        self.opts["worktree"] = not self.opts["worktree"]
        self._show_opts()

    # --------------------------------------------------------------- finish

    @on(Input.Submitted, "#ns-dir")
    def _submit(self) -> None:
        self.action_start()

    def action_start(self) -> None:
        row = self._current()
        if row and row.kind == "up":        # ".." goes up, it never starts anything
            self.action_descend()
            return
        try:
            if not row:
                raise runner.RunError("no folder to start in: type a path, or clear the field to see recent projects")
            folder = runner.check_dir(row.path)
        except runner.RunError as exc:
            self.query_one("#ns-error", Static).update(Text(str(exc), style="bold red"))
            return
        self.dismiss({"cwd": folder, "model": self.opts["model"], "mode": self.opts["mode"], "worktree": self.opts["worktree"]})

    def action_cancel(self) -> None:
        self.dismiss(None)


class FarmApp(App):
    TITLE = "agents-farm"
    CSS = """
    Screen { layout: vertical; }
    #topbar { height: 1; background: $panel; }
    #main { height: 1fr; }
    #left { width: 68; border: round $primary 40%; border-title-color: $text; }
    #left:focus-within { border: round $primary; }
    #filter { display: none; margin: 0 0 0 0; }
    #filter.-visible { display: block; }
    #agents { height: 1fr; background: $surface; }
    #detail { width: 1fr; border: round $secondary 40%; padding: 0 1; border-title-color: $text; }
    #detail:focus-within { border: round $secondary; }
    #d-head { margin-bottom: 1; }
    #d-activity { text-wrap: nowrap; text-overflow: ellipsis; }
    Collapsible { border-top: none; padding: 0; margin: 0; }
    Collapsible > Contents { padding: 0 0 1 2; }
    #limits { height: 1; background: $panel; }
    Screen.-narrow #detail { display: none; }
    Screen.-narrow #left { width: 1fr; }
    Screen.-zoom #left { display: none; }
    Screen.-zoom #detail { display: block; }
    HelpScreen, ConfirmKill, NewSession { align: center middle; }
    ModelPicker { align: center middle; }
    #new-body { width: 92%; max-width: 110; height: 90%; max-height: 30; border: round $primary; border-title-color: $text; background: $surface; padding: 0 1; }
    #new-body Input, #mp-body Input { border: none; height: 1; padding: 0 1; background: $panel; margin-bottom: 1; }
    #ns-main { height: 1fr; }
    #ns-list { width: 1fr; height: 1fr; border: round $primary 40%; border-title-color: $text; background: $surface; }
    #ns-preview { width: 45%; height: 1fr; border: round $secondary 40%; border-title-color: $text; padding: 0 1; }
    #new-body.-narrow #ns-preview { display: none; }
    #ns-opts { height: 1; background: $panel; }
    #ns-error { height: auto; }
    #ns-hints { height: 1; background: $panel; }
    #mp-body { width: 70; max-width: 95%; height: auto; max-height: 24; border: round $primary; border-title-color: $text; background: $surface; padding: 0 1; }
    #mp-list { height: auto; max-height: 14; background: $surface; }
    #mp-error { height: auto; }
    #mp-body Footer { margin-top: 0; }
    #kill-body { width: 82; height: auto; padding: 1 2; border: round $error; background: $panel; }
    #help-body { width: 78; height: auto; padding: 1 2; border: round $primary; background: $panel; }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("z", "zoom", "Zoom"),
        Binding("escape", "back", "Back", show=False),
        Binding("slash", "filter", "Filter"),
        Binding("1", "toggle_section(0)", "Context", show=False),
        Binding("2", "toggle_section(1)", "Activity", show=False),
        Binding("3", "toggle_section(2)", "Plan", show=False),
        Binding("e", "expand_all", "Expand"),
        Binding("h", "toggle_idle", "Idle"),
        Binding("y", "copy_resume", "Copy resume"),
        Binding("p", "copy_pid", "Copy PID", show=False),
        Binding("x", "kill", "Stop process", show=False),
        Binding("n", "new_session", "New session"),
        Binding("o", "open_log", "Log"),
        Binding("r", "refresh_now", "Refresh", show=False),
        Binding("question_mark", "help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, store, interval: float = 2.0, notify_enabled: bool = True):
        super().__init__()
        self.store = store
        self.interval = interval
        self.notify_enabled = notify_enabled
        self.snap: Optional[Snapshot] = None
        self.selected_id: Optional[str] = None
        self.row_keys: List[str] = []
        self.col_keys: list = []
        self.show_idle = False
        self.filter_text = ""
        self._query = Query("")
        self._hl: Dict[str, List[int]] = {}     # agent id -> positions of matched letters in the name
        self.frame = 0
        self._prev_status: Dict[str, Status] = {}
        self._limit_alerts: Set[Tuple[str, str]] = set()
        self._first = True
        self._new_opts: Optional[Dict] = None        # last choices in the new-session dialog
        self._pick_new: Optional[Set[str]] = None   # ids known before `claude` started
        self._windows = getattr(store, "cfg", {}).get("context_window")

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Input(placeholder="search… (apirf)   status:waiting  model:opus  project:x", id="filter")
                yield DataTable(id="agents", cursor_type="row", zebra_stripes=False)
            with VerticalScroll(id="detail"):
                yield Static(id="d-head")
                with Collapsible(title="Context", collapsed=True, id="c-context"):
                    yield Static(id="d-context")
                with Collapsible(title="Activity", collapsed=False, id="c-activity"):
                    yield Static(id="d-activity")
                with Collapsible(title="Plan", collapsed=False, id="c-plan"):
                    yield Static(id="d-plan")
        yield Static(id="limits")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        self.col_keys = [
            table.add_column(" ", key="st", width=3),
            table.add_column("AGENT", key="name", width=R.NAME_WIDTH),
            table.add_column("MODEL", key="model", width=10),
            table.add_column("PID", key="pid", width=7),
            table.add_column("TIME", key="time", width=6),
            table.add_column("CTX", key="ctx", width=4),
        ]
        self.query_one("#left").border_title = "AGENTS"
        self.query_one("#detail").border_title = "DETAILS"
        table.focus()
        self._apply_size(self.size.width)
        self.refresh_data()
        self.set_interval(self.interval, self.refresh_data)
        self.set_interval(0.25, self._spin)

    def on_resize(self, event) -> None:
        self._apply_size(event.size.width)
        if self.snap:
            self._render_limits()

    def _apply_size(self, width: int) -> None:
        self.screen.set_class(width < NARROW_WIDTH, "-narrow")

    # ------------------------------------------------------------------- data

    @work(thread=True, exclusive=True, group="refresh")
    def refresh_data(self) -> None:
        snap = self.store.refresh()
        self.call_from_thread(self._apply_snapshot, snap)

    def _screen_ready(self) -> bool:
        """False while the app is closing: timers and the data worker can still fire once."""
        return len(self.query(DataTable)) > 0

    def _apply_snapshot(self, snap: Snapshot) -> None:
        if not self._screen_ready():
            return
        self._alert_transitions(snap)
        self.snap = snap
        if self._pick_new is not None:
            fresh = [a for a in snap.agents if a.id not in self._pick_new and not a.parent]
            if fresh:
                self.selected_id = max(fresh, key=lambda a: a.last_activity.timestamp() if a.last_activity else 0).id
            self._pick_new = None
        self._render_table()
        self._render_detail()
        self._render_limits()

    def _alert_transitions(self, snap: Snapshot) -> None:
        if not self._first and self.notify_enabled:
            for a in snap.agents:
                prev = self._prev_status.get(a.id)
                if prev != a.status and a.status in (Status.WAITING, Status.ERROR):
                    sev = "warning" if a.status == Status.WAITING else "error"
                    msg = a.status_note or a.status.value
                    self.notify(msg[:200], title=f"{R.STATUS_STYLE[a.status][0]} {a.name[:40]}", severity=sev, timeout=8, markup=False)
                    self.bell()
            for lim in snap.limits:
                p = lim.pct
                key = (lim.family, str(lim.reset_at))
                if p is not None and p >= snap.crit and key not in self._limit_alerts:
                    self._limit_alerts.add(key)
                    self.notify(f"{lim.family} at {p:.0%} of window budget", title="⚠ limit", severity="error", timeout=10, markup=False)
                    self.bell()
        self._prev_status = {a.id: a.status for a in snap.agents}
        self._first = False

    # --------------------------------------------------------------- ordering

    def _visible(self) -> Tuple[List[Agent], int]:
        self._hl = {}
        if not self.snap:
            return [], 0
        q = self._query
        hidden = 0
        scored: Dict[str, float] = {}
        pool: List[Agent] = []
        for a in self.snap.agents:
            if not self.show_idle and not q.active:
                if a.status == Status.IDLE or (a.parent and a.status == Status.DONE):
                    hidden += 1
                    continue
            score = q.score(a)
            if score is None:
                continue
            scored[a.id] = score
            pool.append(a)
            if q.terms:
                self._hl[a.id] = q.name_offsets(a)

        def urgency(a: Agent):
            ts = a.last_activity.timestamp() if a.last_activity else 0
            return (STATUS_ORDER[a.status], -ts)

        def key(a: Agent):
            # With search words the best match comes first; otherwise the most urgent agent.
            return ((-scored[a.id]) if q.ranks else 0, *urgency(a))

        ids = {a.id for a in pool}
        children: Dict[str, List[Agent]] = {}
        roots = []
        for a in pool:
            if a.parent and a.parent in ids:
                children.setdefault(a.parent, []).append(a)
            else:
                roots.append(a)

        # A parent takes the best score and the most urgent status of its children.
        def root_key(a: Agent):
            kids = children.get(a.id, [])
            u = urgency(a)
            for c in kids:
                u = min(u, (urgency(c)[0], u[1]))
            best = max([scored[a.id]] + [scored[c.id] for c in kids])
            return ((-best) if q.ranks else 0, *u)

        out: List[Agent] = []
        for r in sorted(roots, key=root_key):
            out.append(r)
            out.extend(sorted(children.get(r.id, []), key=key))
        return out, hidden

    # ---------------------------------------------------------------- render

    def _render_table(self) -> None:
        if not self.snap:
            return
        table = self.query_one(DataTable)
        rows, hidden = self._visible()
        keys = [a.id for a in rows]
        now = self.snap.updated
        warn, crit = self.snap.warn, self.snap.crit
        if keys != self.row_keys:
            selected = self.selected_id
            table.clear()
            for a in rows:
                table.add_row(*R.row_cells(a, now, self.frame, warn, crit, self._windows, self._hl.get(a.id)), key=a.id)
            self.row_keys = keys
            if selected in keys:
                table.move_cursor(row=keys.index(selected), animate=False)
            elif keys:
                table.move_cursor(row=0, animate=False)
            self.selected_id = keys[table.cursor_row] if keys else None
        else:
            for a in rows:
                for col, cell in zip(self.col_keys, R.row_cells(a, now, self.frame, warn, crit, self._windows, self._hl.get(a.id))):
                    table.update_cell(a.id, col, cell)
        left = self.query_one("#left")
        left.border_title = f"AGENTS ({len(rows)})"
        left.border_subtitle = escape(f"search: {self.filter_text}") if self.filter_text else ""
        self.query_one("#topbar", Static).update(R.top_bar(self.snap, len(rows), hidden))

    def _selected(self) -> Optional[Agent]:
        if not self.snap or not self.selected_id:
            return None
        return next((a for a in self.snap.agents if a.id == self.selected_id), None)

    def _render_detail(self) -> None:
        a = self._selected()
        head = self.query_one("#d-head", Static)
        if not a:
            head.update(Text("No agent selected.\n\nStart a Claude Code session, or press h to show idle ones.", "grey50"))
            for sid in ("#d-context", "#d-activity", "#d-plan"):
                self.query_one(sid, Static).update("")
            return
        snap = self.snap
        head.update(R.detail_header(a, snap.updated, snap.warn, snap.crit, self._windows))
        self.query_one("#d-context", Static).update(R.detail_context(a))
        self.query_one("#d-activity", Static).update(R.detail_activity(a))
        self.query_one("#d-plan", Static).update(R.detail_plan(a))
        self.query_one("#c-context", Collapsible).title = f"Context  ·  {len(a.files)} files"
        self.query_one("#c-activity", Collapsible).title = f"Activity  ·  {len(a.activity)} events"
        prog = R.plan_progress(a)
        self.query_one("#c-plan", Collapsible).title = f"Plan  ·  {prog}" if prog else "Plan"
        self.query_one("#detail").border_title = f"DETAILS · {escape(a.project)}"

    def _render_limits(self) -> None:
        if not self.snap:
            return
        s = self.snap
        self.query_one("#limits", Static).update(R.limits_line(s.limits, s.updated, self.size.width, s.warn, s.crit))

    def _spin(self) -> None:
        if not self.snap or not self._screen_ready():
            return
        self.frame += 1
        table = self.query_one(DataTable)
        for a in self.snap.agents:
            if a.status == Status.THINKING and a.id in self.row_keys:
                table.update_cell(a.id, self.col_keys[0], R.status_cell(a, self.frame))

    # ---------------------------------------------------------------- events

    @on(DataTable.RowHighlighted)
    def _on_highlight(self, event: DataTable.RowHighlighted) -> None:
        table = event.data_table
        if self.row_keys and 0 <= table.cursor_row < len(self.row_keys):
            new = self.row_keys[table.cursor_row]
            if new != self.selected_id:
                self.selected_id = new
                self.query_one("#detail", VerticalScroll).scroll_home(animate=False)
                self._render_detail()

    @on(DataTable.RowSelected)
    def _on_select(self, event: DataTable.RowSelected) -> None:
        self.action_zoom()

    @on(Input.Changed, "#filter")
    def _on_filter(self, event: Input.Changed) -> None:
        self.filter_text = event.value.strip()
        self._query = Query(self.filter_text)
        if self.snap:
            self._render_table()
            self._render_detail()

    @on(Input.Submitted, "#filter")
    def _on_filter_submit(self, event: Input.Submitted) -> None:
        self.query_one(DataTable).focus()

    # --------------------------------------------------------------- actions

    def action_cursor_down(self) -> None:
        self.query_one(DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(DataTable).action_cursor_up()

    def action_zoom(self) -> None:
        if not self.screen.has_class("-zoom"):
            self.screen.add_class("-zoom")
            self.query_one("#c-context", Collapsible).collapsed = False
            self.query_one("#detail", VerticalScroll).focus()
        else:
            self.action_back()

    def action_back(self) -> None:
        flt = self.query_one("#filter", Input)
        if flt.has_focus or (flt.has_class("-visible") and not self.screen.has_class("-zoom")):
            flt.value = ""
            flt.remove_class("-visible")
            self.query_one(DataTable).focus()
            return
        if self.screen.has_class("-zoom"):
            self.screen.remove_class("-zoom")
            self.query_one(DataTable).focus()

    def action_filter(self) -> None:
        self.screen.remove_class("-zoom")
        flt = self.query_one("#filter", Input)
        flt.add_class("-visible")
        flt.focus()

    def action_toggle_section(self, idx: int) -> None:
        ids = ["#c-context", "#c-activity", "#c-plan"]
        c = self.query_one(ids[idx], Collapsible)
        c.collapsed = not c.collapsed

    def action_expand_all(self) -> None:
        cs = list(self.query(Collapsible))
        collapse = all(not c.collapsed for c in cs)
        for c in cs:
            c.collapsed = collapse

    def action_toggle_idle(self) -> None:
        self.show_idle = not self.show_idle
        self.notify("showing idle sessions" if self.show_idle else "idle sessions hidden", timeout=2)
        if self.snap:
            self._render_table()

    def action_copy_resume(self) -> None:
        a = self._selected()
        if not a:
            return
        cmd = f"claude --resume {shlex.quote(a.session_id)}"
        if a.cwd:
            cmd = f"cd {shlex.quote(a.cwd)} && {cmd}"
        self.copy_to_clipboard(cmd)
        self.notify(cmd, title="copied", timeout=4, markup=False)

    def action_copy_pid(self) -> None:
        a = self._selected()
        if not a:
            return
        if not a.pid:
            self.notify("no running process for this agent", timeout=3, markup=False)
            return
        self.copy_to_clipboard(str(a.pid))
        self.notify(f"pid {a.pid}", title="copied", timeout=3, markup=False)

    # ------------------------------------------------------------- stop a process

    def _sessions_dir(self) -> Optional[str]:
        return getattr(getattr(self.store, "registry", None), "root", None)

    def action_kill(self) -> None:
        """x: ask first, then SIGTERM. The checks that make it safe are in killer.py."""
        a = self._selected()
        if not a:
            return
        if not getattr(self.store, "cfg", {}).get("allow_kill", True):
            self.notify("stopping processes is turned off (allow_kill in the config)", timeout=4, markup=False)
            return
        if a.parent:
            self.notify("a subagent has no process of its own: select its parent session", timeout=4, markup=False)
            return
        if not a.pid:
            self.notify("no running process for this agent", timeout=3, markup=False)
            return
        state = a.live_status or {Status.WAITING: "waiting", Status.RUNNING: "busy", Status.THINKING: "busy"}.get(a.status, "")
        target = killer.Target(pid=a.pid, session_id=a.session_id, name=a.name, entrypoint=a.entrypoint, status=state)
        label = R.entry_label(a.entrypoint)
        details: List[Tuple[str, str]] = [
            ("bold", "  " + a.name.replace("\n", " ")[:70]),
            ("grey70", f"  pid {a.pid} · {label}" + (f" · {state}" if state else "")),
            ("", ""),
        ] + [("" if not style else style, "  " + text) for style, text in killer.warnings(a.entrypoint, state, a.session_id)]
        self.push_screen(
            ConfirmKill("Stop this agent's process?", details, "stop it (SIGTERM)"),
            lambda ok: self._confirmed(target, signal.SIGTERM) if ok else None,
        )

    def _confirmed(self, target, sig) -> None:
        if self.snap and self.snap.source == "demo":
            self.notify("demo mode: no signal was sent", timeout=4, markup=False)
            return
        self._send_signal(target, sig)

    @work(thread=True, exclusive=True, group="kill")
    def _send_signal(self, target, sig) -> None:
        wait = killer.TERM_WAIT_S if sig == signal.SIGTERM else killer.KILL_WAIT_S
        try:
            gone = killer.kill(target, sig, self._sessions_dir(), wait_s=wait)
        except killer.KillError as exc:
            self.call_from_thread(self.notify, f"not stopped: {exc}", title=f"pid {target.pid}", severity="error", timeout=8, markup=False)
            return
        self.call_from_thread(self._signal_done, target, sig, gone)

    def _signal_done(self, target, sig, gone: bool) -> None:
        self.refresh_data()
        if gone:
            self.notify(f"pid {target.pid} has stopped", title=killer.SIGNAL_NAMES[sig], timeout=5, markup=False)
        elif sig == signal.SIGTERM:
            self.push_screen(
                ConfirmKill(
                    f"pid {target.pid} did not stop within {killer.TERM_WAIT_S:.0f} seconds",
                    [("", "  SIGKILL cannot be caught: the process gets no chance to save or clean up anything.")],
                    "send SIGKILL",
                ),
                lambda ok: self._send_signal(target, signal.SIGKILL) if ok else None,
            )
        else:
            self.notify(f"pid {target.pid} is still running after SIGKILL", severity="error", timeout=8, markup=False)

    # ------------------------------------------------------------ new session

    def _recent_dirs(self) -> List[str]:
        seen: List[str] = []
        for a in (self.snap.agents if self.snap else []):
            if a.cwd and a.cwd not in seen and os.path.isdir(a.cwd):
                seen.append(a.cwd)
        return seen[:30]

    def action_new_session(self) -> None:
        """n: ask what to start, then give the terminal to `claude` until it exits."""
        a = self._selected()
        cwd = (a.cwd if a and a.cwd and os.path.isdir(a.cwd) else "") or os.getcwd()
        cfg = getattr(self.store, "cfg", {})
        if self._new_opts is None:
            self._new_opts = {"model": str(cfg.get("new_model") or ""), "mode": "default", "worktree": False}
        extra = [m for m in (cfg.get("models") or []) if isinstance(m, str)]
        self.push_screen(NewSession(cwd, list(self.snap.agents) if self.snap else [], self._new_opts, extra), self._start_session)

    def _start_session(self, choice) -> None:
        if not choice:
            return
        self._new_opts = {k: choice[k] for k in ("model", "mode", "worktree")}      # the next dialog starts with the same choices
        if self.snap and self.snap.source == "demo":
            self.notify("demo mode: no session was started", timeout=4, markup=False)
            return
        cfg = getattr(self.store, "cfg", {})
        try:
            claude = runner.find_claude(cfg)
            args = runner.build_args(choice["model"], choice["mode"], choice["worktree"], cfg.get("claude_args"))
            env = runner.build_env(cfg.get("claude_env"))
            cwd = runner.check_dir(choice["cwd"])
        except runner.RunError as exc:
            self.notify(str(exc), title="not started", severity="error", timeout=8, markup=False)
            return
        before = {x.id for x in self.snap.agents} if self.snap else set()
        try:
            with self.suspend():
                code = runner.run_interactive(cwd, args, claude, env)
        except runner.RunError as exc:
            self.notify(str(exc), title="not started", severity="error", timeout=8, markup=False)
            return
        self._pick_new = before
        getattr(self.store, "rediscover", lambda: None)()
        self.refresh_data()
        if code != 0:
            self.notify(f"claude exited with code {code}", severity="warning", timeout=6, markup=False)

    def action_open_log(self) -> None:
        a = self._selected()
        if not a:
            return
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            console = Console(file=fh, force_terminal=True, width=max(self.size.width, 100), color_system="truecolor")
            console.print(R.detail_header(a, self.snap.updated, self.snap.warn, self.snap.crit, self._windows))
            console.rule("Plan")
            console.print(R.detail_plan(a))
            console.rule("Context")
            console.print(R.detail_context(a))
            console.rule("Activity (newest first)")
            console.print(R.detail_activity(a, limit=10_000, wrap=True))
            path = fh.name
        try:
            pager = shlex.split(os.environ.get("PAGER") or "less -R")
        except ValueError:
            pager = ["less", "-R"]
        if pager and os.path.basename(pager[0]) == "less" and "-R" not in pager:
            pager.append("-R")
        try:
            with self.suspend():
                subprocess.call(pager + [path])  # nosec B603
        except (OSError, ValueError) as exc:
            self.notify(f"cannot start pager: {exc}", severity="error", timeout=6, markup=False)
        finally:
            os.unlink(path)

    def action_refresh_now(self) -> None:
        self.refresh_data()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())
