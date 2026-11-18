"""Textual dashboard — layout "A": agents list | details, limits bar at the bottom."""

from __future__ import annotations

import os
import shlex
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
from . import render as R

NARROW_WIDTH = 100

HELP = [
    ("↑↓ / j k", "move between agents"),
    ("enter / z", "zoom: details full screen (esc to go back)"),
    ("1 2 3", "toggle Context / Activity / Plan"),
    ("e", "expand or collapse all sections"),
    ("/", "filter: text, status:waiting, model:opus, project:api"),
    ("h", "show / hide idle sessions and finished subagents"),
    ("y", "copy `claude --resume` command for the agent"),
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


class FarmApp(App):
    TITLE = "agents-farm"
    CSS = """
    Screen { layout: vertical; }
    #topbar { height: 1; background: $panel; }
    #main { height: 1fr; }
    #left { width: 62; border: round $primary 40%; border-title-color: $text; }
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
    HelpScreen { align: center middle; }
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
        self.frame = 0
        self._prev_status: Dict[str, Status] = {}
        self._limit_alerts: Set[Tuple[str, str]] = set()
        self._first = True
        self._windows = getattr(store, "cfg", {}).get("context_window")

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Input(placeholder="filter… status:waiting model:opus project:x", id="filter")
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
            table.add_column("AGENT", key="name", width=24),
            table.add_column("MODEL", key="model", width=10),
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

    def _apply_snapshot(self, snap: Snapshot) -> None:
        self._alert_transitions(snap)
        self.snap = snap
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

    def _matches(self, a: Agent) -> bool:
        if not self.filter_text:
            return True
        for token in self.filter_text.lower().split():
            if ":" in token:
                key, _, val = token.partition(":")
                field = {"status": a.status.value, "model": a.model, "project": a.project + " " + a.cwd}.get(key)
                if field is None or val not in field.lower():
                    return False
            elif token not in " ".join((a.name, a.project, a.prompt, a.model, a.branch)).lower():
                return False
        return True

    def _visible(self) -> Tuple[List[Agent], int]:
        if not self.snap:
            return [], 0
        hidden = 0
        pool = []
        for a in self.snap.agents:
            if not self.show_idle and not self.filter_text:
                if a.status == Status.IDLE or (a.parent and a.status == Status.DONE):
                    hidden += 1
                    continue
            if self._matches(a):
                pool.append(a)

        def key(a: Agent):
            ts = a.last_activity.timestamp() if a.last_activity else 0
            return (STATUS_ORDER[a.status], -ts)

        ids = {a.id for a in pool}
        children: Dict[str, List[Agent]] = {}
        roots = []
        for a in pool:
            if a.parent and a.parent in ids:
                children.setdefault(a.parent, []).append(a)
            else:
                roots.append(a)
        # A parent inherits the urgency of its most urgent child for sorting.
        def root_key(a: Agent):
            k = key(a)
            for c in children.get(a.id, []):
                k = min(k, (key(c)[0], k[1]))
            return k

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
                table.add_row(*R.row_cells(a, now, self.frame, warn, crit, self._windows), key=a.id)
            self.row_keys = keys
            if selected in keys:
                table.move_cursor(row=keys.index(selected), animate=False)
            elif keys:
                table.move_cursor(row=0, animate=False)
            self.selected_id = keys[table.cursor_row] if keys else None
        else:
            for a in rows:
                for col, cell in zip(self.col_keys, R.row_cells(a, now, self.frame, warn, crit, self._windows)):
                    table.update_cell(a.id, col, cell)
        left = self.query_one("#left")
        left.border_title = f"AGENTS ({len(rows)})"
        left.border_subtitle = escape(f"filter: {self.filter_text}") if self.filter_text else ""
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
        if not self.snap:
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
