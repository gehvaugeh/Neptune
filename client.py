import os
import json
import asyncio
import re
import time
import argparse
import logging
import pyte
import inspect
from functools import wraps

# Global Monkeypatch for pyte to handle 'private' keyword argument in CSI sequences.
# pyte.Stream passes 'private=True' to Screen methods when it encounters CSI sequences starting with '?'.
# However, many Screen methods (like select_graphic_rendition) do not accept this argument, causing TypeErrors.
# This patch automatically wraps all Screen/HistoryScreen methods to ignore 'private' if they don't support it.
def _patch_pyte():
    for cls in [pyte.Screen, pyte.HistoryScreen]:
        for name, attr in inspect.getmembers(cls, predicate=inspect.isfunction):
            if not name.startswith("__"):
                try:
                    sig = inspect.signature(attr)
                    has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                    if 'private' not in sig.parameters and not has_kwargs:
                        def make_wrapper(func):
                            @wraps(func)
                            def wrapper(*args, **kwargs):
                                kwargs.pop('private', None)
                                return func(*args, **kwargs)
                            return wrapper
                        setattr(cls, name, make_wrapper(attr))
                except (ValueError, TypeError):
                    continue
_patch_pyte()

from typing import List, Dict

from rich.text import Text
from rich.style import Style
from rich.markup import escape
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, OptionList, Label, TextArea, Markdown, Button, Input, Checkbox
from textual.command import Provider, Hit
from textual.widgets.option_list import Option
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.binding import Binding
from textual.screen import ModalScreen
from textual import work, on, events, message

from common import HistoryManager, fuzzy_match, load_workflows, get_random_bright_color, THEME_FILE, REMOTE_HOSTS_FILE, get_current_token
from autocomplete import BashAutocompleteProvider, CmdAutocompleteProvider, LocalFileProvider
from markdown_toolbox import MarkdownToolboxPanel, MdElementSelected
from pty_manager_ui import PTYManagerModal, RemotePTYAuthModal

# Setup client logging
logging.basicConfig(
    filename='client_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s'
)

class ServerMessage(message.Message):
    def __init__(self, data: Dict) -> None:
        self.data = data
        super().__init__()

DEFAULT_SOCKET_PATH = "/tmp/neptune.sock"

class NeptuneCommandProvider(Provider):
    async def search(self, query: str) -> ComposeResult:
        matcher = self.matcher(query)
        commands = [
            ("PTY Manager", "spawn_pty_manager", "Open PTY Manager overlay"),
            ("Change Block PTY", "change_pty", "Change target PTY of selected command block"),
            ("Export Notebook", "save_notebook_dialog", "Save current session as Markdown"),
            ("Import Notebook", "import_notebook_dialog", "Load blocks from Markdown"),
            ("Clear Session", "clear_session", "Remove all blocks and reset server state"),
            ("Exit", "quit", "Close Neptune"),
            ("Save Workflow", "save_workflow_from_input", "Save current input as workflow"),
        ]
        for name, action, desc in commands:
            score = matcher.match(name)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(name),
                    lambda action=action: getattr(self.app, f"action_{action}")(),
                    help=desc
                )

# --- MODALE DIALOGE ---

# The following modals were moved to pty_manager_ui.py:
# - RemotePTYAuthModal
# - PTYPicker (replaced by PTYManagerModal)

class SaveNotebookModal(ModalScreen):
    def compose(self) -> ComposeResult:
        with Vertical(id="modal_dialog"):
            yield Label("Notebook exportieren (.md)", classes="modal-title")
            yield Input(placeholder="dateiname.md", id="file_name", value=f"session_{int(time.time())}.md")
            yield Checkbox("Include Output", value=True, id="include_output")
            with Horizontal(id="modal_buttons"):
                yield Button("Abbrechen", variant="error", id="cancel")
                yield Button("Exportieren", variant="success", id="export")
    @on(Button.Pressed, "#cancel")
    def cancel(self): self.dismiss(None)
    @on(Button.Pressed, "#export")
    def export(self):
        name = self.query_one("#file_name").value
        if not name.endswith(".md"): name += ".md"
        include_output = self.query_one("#include_output").value
        self.dismiss((name, include_output))

class ImportNotebookModal(ModalScreen):
    def compose(self) -> ComposeResult:
        with Vertical(id="modal_dialog"):
            yield Label("Notebook importieren (.md)", classes="modal-title")
            yield Input(placeholder="dateiname.md", id="file_name")
            yield Checkbox("Include Output", value=True, id="include_output")
            with Horizontal(id="modal_buttons"):
                yield Button("Abbrechen", variant="error", id="cancel")
                yield Button("Importieren", variant="success", id="import")
    @on(Button.Pressed, "#cancel")
    def cancel(self): self.dismiss(None)
    @on(Button.Pressed, "#import")
    def import_nb(self):
        name = self.query_one("#file_name").value
        include_output = self.query_one("#include_output").value
        self.dismiss((name, include_output))


class SaveWorkflowModal(ModalScreen):
    def __init__(self, text: str):
        super().__init__()
        self.text = text

    def on_key(self, event: events.Key):
        if event.key == "ctrl+s":
            event.stop()
            event.prevent_default()
            self.save()

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_dialog"):
            yield Label("Save as Workflow", classes="modal-title")
            yield Input(placeholder="Name...", id="wf_name")
            yield TextArea(self.text, id="wf_cmd", language="bash")
            with Horizontal(id="modal_buttons"):
                yield Button("Cancel", variant="error", id="cancel")
                yield Button("Save", variant="success", id="save")
    @on(Button.Pressed, "#cancel")
    def cancel(self): self.dismiss(None)
    @on(Button.Pressed, "#save")
    def save(self):
        n, c = self.query_one("#wf_name").value, self.query_one("#wf_cmd").text
        if n and c:
            self.dismiss((n, c))

class ExitConfirmModal(ModalScreen):
    def __init__(self, block_count: int, minutes_since_export: int):
        super().__init__()
        self.block_count = block_count
        self.minutes_since_export = minutes_since_export

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_dialog"):
            yield Label("Unsaved Changes?", classes="modal-title")
            yield Label(f"Blocks: [bold]{self.block_count}[/]")
            yield Label(f"Last export: [bold]{self.minutes_since_export}[/] minute(s) ago")
            yield Label("Your notebook may have unsaved changes.", classes="modal-hint")
            with Horizontal(id="modal_buttons"):
                yield Button("No & Exit", variant="error", id="no_exit")
                yield Button("Cancel", variant="primary", id="cancel")

    @on(Button.Pressed, "#cancel")
    def cancel(self): self.dismiss(None)
    @on(Button.Pressed, "#no_exit")
    def no_exit(self): self.dismiss("exit")

    def on_key(self, event: events.Key):
        if event.key == "escape": self.dismiss(None)

# --- BLOCKS ---

class BlockEditor(TextArea):
    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            node = self.parent
            while node and not hasattr(node, "toggle_edit"):
                node = node.parent
            if node: asyncio.create_task(node.toggle_edit(save=False))
        elif event.key == "ctrl+j":
            event.stop()
            event.prevent_default()
            node = self.parent
            while node and not hasattr(node, "toggle_edit"):
                node = node.parent
            if node: asyncio.create_task(node.toggle_edit(save=True))

class BaseBlock(Static):
    can_focus = True
    def __init__(self, block_id, content, app_ref, is_editing=False, editing_content=None, cursor_pos=None, **kwargs):
        super().__init__(**kwargs)
        self.block_id = block_id
        self.content = content
        self.app_ref = app_ref
        self.is_editing = is_editing
        self.editing_content = editing_content or content
        self.cursor_pos = cursor_pos
        self.locked_by = None
        self.lock_color = None
        self.last_click_time = 0

    def update_lock(self, user_id, user_color):
        self.locked_by = user_id
        self.lock_color = user_color
        if user_id:
            # Visual feedback for lock: Right border in user's color
            self.styles.border_right = ("thick", user_color)
            if user_id != self.app_ref.user_id:
                self.query_one("#block_text_edit").disabled = True
                self.add_class("locked-remote")
            else:
                self.query_one("#block_text_edit").disabled = False
                self.add_class("locked-local")
        else:
            self.styles.border_right = None
            self.query_one("#block_text_edit").disabled = False
            self.remove_class("locked-remote")
            self.remove_class("locked-local")

    def on_focus(self, event: events.Focus) -> None:
        if self.is_editing:
            self.query_one("#block_text_edit").focus()
        if self.app_ref.input_mode == "SELECTION":
            self.app_ref.last_selected_block_id = self.block_id

    def on_mount(self) -> None:
        if self.is_editing and self.cursor_pos:
            edit = self.query_one("#block_text_edit")
            edit.cursor_location = self.cursor_pos

        if isinstance(self, CommandBlock):
            self.query_one("#output").styles.max_height = self.app_ref.preferred_rows

class NoteBlock(BaseBlock):
    def compose(self) -> ComposeResult:
        render_classes = "markdown-content" + (" hidden" if self.is_editing else "")
        edit_classes = "" if self.is_editing else "hidden"

        yield Markdown(self.content, id="md_render", classes=render_classes)
        yield BlockEditor(self.editing_content, id="block_text_edit", classes=edit_classes, language="markdown")
        yield Label("Note (esc: leave edit | ctrl+j: save)", classes="block-info")

    async def toggle_edit(self, remote=False, save=True, restore=False):
        if not remote and self.locked_by and self.locked_by != self.app_ref.user_id:
            user_info = self.app_ref.users.get(self.locked_by, {})
            user_label = user_info.get("name", self.locked_by[:4])
            self.app_ref.notify(f"Block is locked by user {user_label}", severity="warning")
            return

        if not restore:
            self.is_editing = not self.is_editing

        render, edit = self.query_one("#md_render"), self.query_one("#block_text_edit")

        if self.is_editing:
            render.add_class("hidden")
            edit.remove_class("hidden")
            if not remote:
                if not restore:
                    lines = edit.document.lines
                    if lines:
                        edit.cursor_location = (len(lines)-1, len(lines[-1]))
                edit.focus()
                self.app_ref.enter_blockedit_mode()
                if not restore:
                    await self.app_ref.send_message({"type": "edit_start", "block_id": self.block_id})
        else:
            if not remote:
                if save:
                    self.content = edit.text
                    await self.app_ref.send_message({"type": "edit_save", "block_id": self.block_id, "content": self.content})
                else:
                    edit.text = self.content
                    await self.app_ref.send_message({"type": "edit_cancel", "block_id": self.block_id})

            render.update(self.content)
            render.remove_class("hidden")
            edit.add_class("hidden")
            if not remote:
                if self.app_ref.was_in_selection_mode:
                    self.app_ref.enter_selection_mode()
                else:
                    self.app_ref.enter_normal_mode()

class NotebookInput(TextArea):
    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            # For BASH and NOTE modes, regular Enter submits.
            # CMD mode always uses single line, so Enter always submits.
            if self.app.input_mode == "CMD":
                event.stop(); event.prevent_default()
                asyncio.create_task(self.app.action_submit())
            else:
                # In BASH/NOTE, only submit if not using Ctrl/Shift/Alt modifiers
                # However, Textual 'enter' key event usually doesn't include modifiers like ctrl+enter
                # as separate flags in the key string itself, but we check the specific key name.
                event.stop(); event.prevent_default()
                asyncio.create_task(self.app.action_submit())
        elif event.key in ("ctrl+enter", "ctrl+j", "ctrl+m", "shift+enter", "shift+return"):
            # Allow multiline for BASH and NOTE
            if self.app.input_mode in ("BASH", "NOTE"):
                event.stop(); event.prevent_default()
                self.insert("\n")
            else:
                event.stop(); event.prevent_default()
                asyncio.create_task(self.app.action_submit())
        elif event.key == "ctrl+s":
            if self.app.input_mode == "BASH":
                event.stop(); event.prevent_default()
                self.app.action_save_workflow(self.text)
        elif event.key == "escape":
            event.stop()
            event.prevent_default()
            self.app.action_esc_pressed()

class CommandBlock(BaseBlock):
    def __init__(self, block_id, command, cwd, app_ref, is_editing=False, editing_content=None, cursor_pos=None, pty_uid=0, pty_name="local-0", **kwargs):
        super().__init__(block_id, command, app_ref, is_editing, editing_content, cursor_pos, **kwargs)
        self.cwd = cwd
        self.pty_uid = pty_uid
        self.pty_name = pty_name
        self.output = ""
        # Initialize with fixed TTY dimensions established by the app
        self.terminal_screen = pyte.HistoryScreen(app_ref.preferred_cols, app_ref.preferred_rows, history=1000)
        self.stream = pyte.Stream(self.terminal_screen)
        self._style_cache = {}
        self._color_error = False
        self._last_status_text = "Ready"
        self.zoomed = False
        self._spinner_task = None

    def compose(self) -> ComposeResult:
        label_classes = "" if not self.is_editing else "hidden"
        edit_classes = "" if self.is_editing else "hidden"

        header_text = f"[bold blue]{escape(self.cwd)}[/]"
        header_text = f"[bold cyan][{escape(self.pty_name)}][/] {header_text}"

        with Horizontal(classes="block-header"):
            yield Label("➜", classes="prompt-symbol")
            yield Label(f"{header_text}\n[white]{escape(self.content)}[/]", id="cmd_label", classes=label_classes)
            yield BlockEditor(self.editing_content, id="block_text_edit", classes=edit_classes, language="bash")
        yield Static("", id="output", classes="block-output", markup=False)
        pty_id_display = str(self.pty_uid) if self.pty_uid is not None else "???"
        yield Label(f"[grey44]Ready[/] [cyan][{self.pty_name} (ID:{pty_id_display})][/]", id="info", classes="block-info")

    def on_resize(self, event: events.Resize) -> None:
        try:
            out = self.query_one("#output")
            new_cols = out.content_region.width
            if new_cols >= 40 and new_cols != self.terminal_screen.columns:
                self.terminal_screen.resize(self.terminal_screen.lines, new_cols)
                self.render_terminal()
                if self.pty_uid is not None:
                    asyncio.create_task(self.app.send_message({
                        "type": "terminal_resize",
                        "pty_uid": self.pty_uid,
                        "rows": self.terminal_screen.lines,
                        "cols": new_cols,
                    }))
        except:
            pass

    def append_output(self, text: str):
        if not isinstance(text, str):
            text = text.decode(errors="replace")

        self.output += text
        if len(self.output) > 1_000_000:
            self.output = self.output[-1_000_000:]

        self.stream.feed(text)
        if self.is_mounted:
            self.render_terminal()

    def render_terminal(self):
        if not self.is_mounted: return
        self._color_error = False
        # We always use the pyte screen for rendering to ensure consistent VT100 support
        rich_text = Text()

        cursor_x, cursor_y = self.terminal_screen.cursor.x, self.terminal_screen.cursor.y
        # Only show cursor if in interactive mode, and respect cursor visibility mode from PTY
        show_cursor = (self.app_ref.input_mode == "CONTROL" and self.app_ref.focused == self) and not self.terminal_screen.cursor.hidden

        def append_line(y, line):
            if not line:
                if show_cursor and y == cursor_y:
                    # Render cursor even on empty line
                    rich_text.append(" ", style="reverse")
                rich_text.append("\n")
                return

            # Ensure line is a list of characters (History lines are lists, Buffer lines are dicts)
            if not isinstance(line, list):
                line = [line[x] for x in range(self.terminal_screen.columns)]

            current_style = self._get_rich_style(line[0])
            current_text = ""
            for x, char in enumerate(line):
                char_style = self._get_rich_style(char)

                # Apply cursor style if needed
                if show_cursor and y == cursor_y and x == cursor_x:
                     # Flush current text
                     rich_text.append(current_text, style=current_style)
                     # Render cursor char (usually space or current char with reverse)
                     # No blink as requested, just steady reverse.
                     rich_text.append(char.data or " ", style="reverse" if not char_style else f"{char_style} reverse")
                     # Reset for next chars
                     current_style = char_style
                     current_text = ""
                     continue

                if char_style == current_style:
                    current_text += char.data
                else:
                    rich_text.append(current_text, style=current_style)
                    current_style = char_style
                    current_text = char.data
            rich_text.append(current_text, style=current_style)
            rich_text.append("\n")

        # Prepend history only if NOT running, to keep TUI layouts stable
        is_running = getattr(self, "_last_status", "") == "running"
        if self.app_ref.input_mode != "CONTROL" and not is_running:
            for line_obj in self.terminal_screen.history.top:
                append_line(-1, line_obj)
            for line_obj in self.terminal_screen.history.bottom:
                append_line(-1, line_obj)

        # Find the last non-empty line (considering data and non-default background/formatting)
        # We always do this compact rendering to avoid empty trailing space
        end_y = self.terminal_screen.lines
        for y in range(self.terminal_screen.lines - 1, -1, -1):
            row = self.terminal_screen.buffer[y]
            is_empty = True
            if y == cursor_y and show_cursor:
                 is_empty = False
            else:
                for x in range(self.terminal_screen.columns):
                    char = row[x]
                    if char.data != ' ' or char.bg != 'default' or char.reverse:
                        is_empty = False
                        break
            if not is_empty:
                end_y = y + 1
                break
        else:
            end_y = 1 # Keep at least one line

        for y in range(end_y):
            append_line(y, self.terminal_screen.buffer[y])

        # Optimize: Only update if content or cursor changed
        out_widget = self.query_one("#output")
        cache_key = (str(rich_text), cursor_x, cursor_y, show_cursor)
        if getattr(out_widget, "_last_render_key", None) != cache_key:
            out_widget.update(rich_text)
            out_widget._last_render_key = cache_key

        if self._color_error:
            info = self.query_one("#info")
            if "⚠" not in str(info.renderable):
                info.update(f"{self._last_status_text} [dim]⚠ color error[/]")

    def _get_rich_style(self, char):
        # Cache key based on char attributes that affect style
        cache_key = (char.fg, char.bg, char.bold, char.italics, char.underscore, char.reverse)
        if cache_key in self._style_cache:
            style, is_err = self._style_cache[cache_key]
            if is_err: self._color_error = True
            return style

        def map_color(c):
            if not c or c == "default": return None
            # Pyte color names to Rich-compatible names
            mapping = {
                "brown": "yellow",
                "lightgray": "white",
                "darkgray": "bright_black",
            }
            if isinstance(c, str):
                c = mapping.get(c, c)
                if c.startswith("bright") and "_" not in c:
                    c = c.replace("bright", "bright_")

                # Check for hex colors (6 or 8 hex digits)
                if re.fullmatch(r"[0-9a-fA-F]{6}|[0-9a-fA-F]{8}", c):
                    return f"#{c[:6]}"
            return c

        fg = map_color(char.fg)
        bg = map_color(char.bg)

        is_err = False
        try:
            parts = []
            if fg: parts.append(fg if (not isinstance(fg, str) or not fg.isdigit()) else f"color({fg})")
            if bg: parts.append(f"on {bg}" if (not isinstance(bg, str) or not bg.isdigit()) else f"on color({bg})")
            if char.bold: parts.append("bold")
            if char.italics: parts.append("italic")
            if char.underscore: parts.append("underline")
            if char.reverse: parts.append("reverse")

            style = Style.parse(" ".join(parts))
        except Exception:
            self._color_error = True
            is_err = True
            # Fallback: keep non-color attributes
            parts = []
            if char.bold: parts.append("bold")
            if char.italics: parts.append("italic")
            if char.underscore: parts.append("underline")
            if char.reverse: parts.append("reverse")
            style = Style.parse(" ".join(parts)) if parts else Style.null()

        self._style_cache[cache_key] = (style, is_err)
        return style

    def update_header(self):
        if not self.is_mounted: return
        label = self.query_one("#cmd_label")
        header_text = f"[bold blue]{escape(self.cwd)}[/]"
        header_text = f"[bold cyan][{escape(self.pty_name)}][/] {header_text}"
        label.update(f"{header_text}\n[white]{escape(self.content)}[/]")

    def _build_info_text(self, icon="") -> str:
        pty_id_display = str(self.pty_uid) if self.pty_uid is not None else "???"
        pty_info = f" [cyan][{self.pty_name} (ID:{pty_id_display})][/]"
        text = f"{self._last_status_text}{icon}{pty_info}"
        if self._color_error:
            text += " [dim]⚠ color error[/]"
        return text

    def _start_spinner(self):
        if self._spinner_task:
            return
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        async def _animate():
            i = 0
            try:
                while True:
                    icon = f" {frames[i % len(frames)]}"
                    if self.app_ref.input_mode == "CONTROL" and self.app_ref.focused == self:
                        icon += " [interactive] TUI"
                    try:
                        self.query_one("#info").update(self._build_info_text(icon))
                    except:
                        break
                    i += 1
                    await asyncio.sleep(0.08)
            except asyncio.CancelledError:
                pass
            except:
                pass
        self._spinner_task = asyncio.create_task(_animate())

    def _stop_spinner(self):
        if self._spinner_task:
            self._spinner_task.cancel()
            self._spinner_task = None

    def update_status(self, status):
        if not self.is_mounted: return
        self._stop_spinner()
        info = self.query_one("#info")

        if status == "running":
            self._last_status_text = "[yellow]Running...[/]"
            self.add_class("running")
            self._start_spinner()
            return
        elif "queued" in status:
            num = status.split("(")[1].split(")")[0]
            self._last_status_text = f"[blue]⏳ In Queue (#{num})[/]"
            self.remove_class("running")
            icon = " ⏳"
        elif status == "ok":
            self._last_status_text = "[green]✅ OK[/]"
            self.remove_class("running")
            icon = " ✓"
        elif "error" in status:
            self._last_status_text = f"[red]❌ {status.upper()}[/]"
            self.remove_class("running")
            icon = " ✗"
        else:
            self._last_status_text = f"[grey44]{status.capitalize()}[/]"
            icon = ""

        if self.app_ref.input_mode == "CONTROL" and self.app_ref.focused == self:
            icon += " [interactive] TUI"

        info.update(self._build_info_text(icon))

    async def toggle_edit(self, remote=False, save=True, restore=False):
        if not remote and self.locked_by and self.locked_by != self.app_ref.user_id:
            user_info = self.app_ref.users.get(self.locked_by, {})
            user_label = user_info.get("name", self.locked_by[:4])
            self.app_ref.notify(f"Block is locked by user {user_label}", severity="warning")
            return

        if not restore:
            self.is_editing = not self.is_editing

        label, edit = self.query_one("#cmd_label"), self.query_one("#block_text_edit")

        if self.is_editing:
            label.add_class("hidden")
            edit.remove_class("hidden")
            if not remote:
                if not restore:
                    lines = edit.document.lines
                    if lines:
                        edit.cursor_location = (len(lines)-1, len(lines[-1]))
                edit.focus()
                self.app_ref.enter_blockedit_mode()
                if not restore:
                    await self.app_ref.send_message({"type": "edit_start", "block_id": self.block_id})
        else:
            if not remote:
                if save:
                    self.content = edit.text
                    await self.app_ref.send_message({"type": "edit_save", "block_id": self.block_id, "content": self.content})
                else:
                    edit.text = self.content
                    await self.app_ref.send_message({"type": "edit_cancel", "block_id": self.block_id})

            self.update_header()
            label.remove_class("hidden")
            edit.add_class("hidden")
            if not remote:
                if self.app_ref.was_in_selection_mode:
                    self.app_ref.enter_selection_mode()
                else:
                    self.app_ref.enter_normal_mode()

# --- APP ---

class ClientApp(App):
    CSS_PATH = THEME_FILE
    COMMANDS = {NeptuneCommandProvider}

    def _on_mouse_event(self, event: events.MouseEvent) -> None:
        event.stop()
        event.prevent_default()

    BINDINGS = [
        Binding("ctrl+q", "quit", "Exit"),
        Binding("ctrl+f", "toggle_filter", "Filter"),
        Binding("ctrl+g", "remove_filter", "Remove Filter"),
        Binding("ctrl+t", "spawn_pty_manager", "PTY Manager"),
        Binding("escape", "esc_pressed", "Back/Clear")
    ]

    def action_quit(self):
        container = self.query_one("#command_history")
        blocks = [c for c in container.children if isinstance(c, BaseBlock)]
        if not blocks:
            self._do_shutdown()
            return
        seconds_since_export = time.time() - self.last_export_time
        if seconds_since_export < 120:
            self._do_shutdown()
            return
        minutes = int(seconds_since_export / 60)
        self.push_screen(ExitConfirmModal(len(blocks), minutes), self._on_exit_confirm)

    def _on_exit_confirm(self, result):
        if result == "exit":
            self._do_shutdown()

    def __init__(self, socket_path=DEFAULT_SOCKET_PATH):
        super().__init__()
        self.socket_path = socket_path
        self.history = HistoryManager()
        self.preferred_cols = 80
        self.preferred_rows = 24
        self.input_mode = "NORMAL"
        self.user_color = get_random_bright_color()
        self.user_name = os.environ.get("USER", "User")
        self.user_id = None
        self.blocks = {}
        self.users = {}
        self.reader = None
        self.writer = None
        self.previous_filter = ""
        self._suppress_search = False
        self.workflows = load_workflows()
        self.yank_buffer = None
        self.last_selected_block_id = None
        self.was_in_selection_mode = False
        self.insert_after_id = None
        self.count_str = ""
        self.last_escape_time = 0
        self._autocomplete_futures = {}
        self._last_suggestions = []

        # PTY State
        self.ptys: Dict[int, Dict] = {
            0: {"type": "local", "status": "idle", "block_count": 0, "name": "local-0"}
        }
        self.default_pty_uid = 0
        self.last_remote_pty_uid = None
        self.bang_time = 0.0
        self.remote_hosts = self._load_remote_hosts()
        self.last_export_time = time.time()

        self.available_commands = [
            {"name": "ptyman", "params": "", "desc": "Open PTY Manager overlay"},
            {"name": "export", "params": "[file]", "desc": "Save current session as a Markdown file"},
            {"name": "import", "params": "[file]", "desc": "Load blocks from an external Markdown file"},
            {"name": "exit", "params": "", "desc": "Close the client and return to terminal"},
            {"name": "save_wf", "params": "", "desc": "Save the command in main input as a Workflow"},
            {"name": "help", "params": "", "desc": "Show list of available internal commands"},
            {"name": "clear", "params": "", "desc": "Remove all blocks and reset server shell state"},
        ]
        self.providers = {
            "BASH": BashAutocompleteProvider(),
            "CMD": CmdAutocompleteProvider(self.available_commands),
        }

    def _load_remote_hosts(self) -> List[str]:
        if os.path.exists(REMOTE_HOSTS_FILE):
            try:
                with open(REMOTE_HOSTS_FILE) as f:
                    return [l.strip() for l in f if l.strip()]
            except:
                pass
        return []

    def _save_remote_host(self, entry: str):
        if entry not in self.remote_hosts:
            self.remote_hosts.append(entry)
            try:
                with open(REMOTE_HOSTS_FILE, "a") as f:
                    f.write(f"{entry}\n")
            except:
                pass

    def compose(self) -> ComposeResult:
        with Horizontal(id="filter_bar", classes="hidden"):
            yield Label(" 🔍 Filter: ", id="filter_label")
            f_inp = Input(placeholder="Search blocks...", id="filter_input")
            f_inp.tooltip = "Enter text to filter blocks by command or output content."
            yield f_inp
        with Horizontal(id="pty_target_bar", classes="hidden"):
            yield Label(" 🌐 PTY Target: ", id="pty_target_label")
            p_inp = Input(placeholder="local | user@host | user@host:key | pty_id", id="pty_target_input")
            yield p_inp
##        with ScrollableContainer(id="command_history"):
        yield ScrollableContainer(id="command_history")
#            yield Static("[bold #81d4fa]Neptune Multi-User | Collaborative Notebook[/]", id="notebook_header")
        with Vertical(id="bottom_dock") as dock:
            dock.can_focus = True
            yield MarkdownToolboxPanel(id="md_toolbox")
            yield OptionList(id="palette")
            with Horizontal(id="dock_status_bar"):
                self.mode_label = Label("MODE: NORMAL", id="mode_indicator")
                self.mode_label.tooltip = "Current interaction mode (NORMAL, BASH, CMD, NOTE, SELECTION, BLOCKEDIT)"
                yield self.mode_label
                yield Label("⟳", id="autocomplete_spinner", classes="hidden")
            with Horizontal(id="input_container"):
                yield Label("", id="mode_prefix")
                self.user_label = Label(f"User: [bold {self.user_color}]Me[/]", id="user_indicator")
                self.user_label.tooltip = "Your current username and unique color identifier."
                yield self.user_label
                m_inp = NotebookInput(language="bash", id="main_input")
                m_inp.tooltip = "Main command input. Use !, :, or ; in NORMAL mode to change input types."
                yield m_inp

    def on_mount(self):
        self.preferred_cols = max(40, self.screen.size.width - 14)
        self.preferred_rows = 24

        # Register exception handler for crash autosave
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(self._exception_handler)

        self.run_worker(self.connect_to_server(), group="server")
        self.enter_normal_mode()

    def on_ready(self):
        self.call_after_refresh(lambda: self.query_one("#bottom_dock").focus())
    def _exception_handler(self, loop, context):
        exc = context.get("exception")
        if exc:
            self._autosave_on_crash(exc)
        loop.default_exception_handler(context)

    def _autosave_on_crash(self, exc=None):
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"autosave_crash_{timestamp}.md"
        try:
            md_output = [f"# Neptune Crash Recovery - {time.strftime('%Y-%m-%d %H:%M:%S')}\n"]
            md_output.append(f"\n_This is an automatic backup from an unexpected shutdown._\n")
            if exc:
                md_output.append(f"\n**Error:** `{type(exc).__name__}: {exc}`\n")
            container = self.query_one("#command_history")
            for block in container.children:
                if isinstance(block, NoteBlock):
                    md_output.append(f"{block.content}\n")
                elif isinstance(block, CommandBlock):
                    pty_uid_export = block.pty_uid if block.pty_uid is not None else 0
                    md_output.append(f"```bash (uid:{pty_uid_export})\n{block.content}\n```\n")
                    if block.output:
                        clean = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', block.output)
                        if clean.strip():
                            md_output.append(f"```text\n{clean.rstrip()}\n```\n")
            with open(filename, "w") as f:
                f.write("\n".join(md_output))
            self.notify(f"CRASH RECOVERY: Autosaved to {filename}", severity="warning")
        except Exception as e:
            self.notify(f"Autosave failed: {e}", severity="error")

    async def connect_to_server(self):
        logging.debug(f"Client: connect_to_server starting, socket={self.socket_path}")
        try:
            self.reader, self.writer = await asyncio.open_unix_connection(
                self.socket_path, limit=10 * 1024 * 1024
            )
            logging.debug(f"Client: connected ok, writer={id(self.writer) if self.writer else 'None'}")
            await self.send_message({
                "type": "connect",
                "color": self.user_color,
                "user": self.user_name
            })
            # Set fixed TTY size on server
            await self.send_message({
                "type": "terminal_resize",
                "rows": self.preferred_rows,
                "cols": self.preferred_cols
            })
            await self.listen_to_server()
        except Exception as e:
            self.notify(f"Could not connect to server: {e}", severity="error")

    async def listen_to_server(self):
        reader_id = id(self.reader)
        logging.debug(f"Client: listen_to_server STARTING reader={reader_id}")
        while self.reader and not self.reader.at_eof():
            try:
                raw = await self.reader.readline()
                if not raw:
                    logging.debug("Client: listen_to_server got empty line (EOF)")
                    break
                decoded = raw.decode("utf-8", errors="replace")
                data = decoded.strip()
                if not data:
                    logging.debug("Client: listen_to_server got blank line")
                    continue
                logging.debug(f"Client: listen_to_server packet: {decoded[:300]!r}")
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError as e:
                    logging.error(f"Client: listen_to_server JSON error: {e}")
                    continue
                # Resolve autocomplete futures directly
                if msg.get("type") == "autocomplete_response":
                    rid = msg.get("request_id")
                    results = msg.get("results", [])
                    logging.debug(f"Client: listen_to_server got autocomplete_response RID={rid}, {len(results)} items")
                    if rid in self._autocomplete_futures:
                        self._autocomplete_futures[rid].set_result(results)
                        logging.debug(f"Client: Future set for RID {rid}")
                    else:
                        logging.warning(f"Client: No future found for RID {rid}")
                else:
                    self.post_message(ServerMessage(msg))
            except Exception as e:
                logging.error(f"Client: listen_to_server read error: {type(e).__name__}: {e}")
                break
        logging.debug(f"Client: listen_to_server STOPPED reader={reader_id} at_eof={self.reader and self.reader.at_eof() or 'N/A'}")

    async def send_message(self, msg):
        if self.writer:
            try:
                self.writer.write(json.dumps(msg).encode() + b"\n")
                await self.writer.drain()
            except: pass

    async def on_server_message(self, event: ServerMessage):
        msg = event.data
        msg_type = msg.get("type")
        if msg_type not in ("output", "queue_status", "pty.list"):
            logging.debug(f"Client: Received server message type: {msg_type}")

        if msg_type == "init":
            focused_id, editing_id, editing_content, cursor_pos = None, None, None, None
            focused = self.focused
            temp_focused = focused
            while temp_focused and not isinstance(temp_focused, BaseBlock):
                temp_focused = temp_focused.parent
            if isinstance(temp_focused, BaseBlock):
                focused_id = temp_focused.block_id
                if temp_focused.is_editing:
                    editing_id = focused_id
                    try:
                        edit_widget = temp_focused.query_one("#block_text_edit")
                        editing_content = edit_widget.text
                        cursor_pos = edit_widget.cursor_location
                    except: pass
            elif focused and focused.id == "main_input":
                focused_id = "main_input"

            new_id = msg.get("your_id")
            if new_id and new_id != "all": self.user_id = new_id
            self.users = msg.get("users", {})
            container = self.query_one("#command_history")
            for b_id in list(self.blocks.keys()):
                try: self.blocks[b_id].remove()
                except: pass
            self.blocks = {}
            for block_data in msg.get("blocks", []):
                b_id = block_data.get("id")
                is_editing = (b_id == editing_id)
                await self.create_block(
                    block_data,
                    is_editing=is_editing,
                    editing_content=editing_content if is_editing else None,
                    cursor_pos=cursor_pos if is_editing else None
                )
            if focused_id == "main_input":
                self.query_one("#main_input").focus()
            elif focused_id and focused_id in self.blocks:
                self.call_after_refresh(self.blocks[focused_id].focus)

            if "ptys" in msg:
                for p in msg.get("ptys", []):
                    uid = p.get("uid")
                    self.ptys[uid] = {
                        "type": p.get("type", "local"),
                        "status": p.get("status", "idle"),
                        "block_count": p.get("block_count", 0),
                        "active_block_id": p.get("active_block_id"),
                        "name": p.get("name")
                    }

        elif msg_type == "user_join":
            u_id, u_col, u_name = msg.get("user_id"), msg.get("color"), msg.get("name")
            self.users[u_id] = {"color": u_col, "name": u_name}
            self.notify(f"User {u_name} joined", severity="information")

        elif msg_type == "user_leave":
            u_id = msg.get("user_id")
            if u_id in self.users:
                del self.users[u_id]
                self.notify(f"User {u_id[:4]} left", severity="information")

        elif msg_type == "new_block":
            block_data = msg.get("block")
            await self.create_block(block_data)
            if block_data.get("type") == "CMD":
                self.history.add(block_data.get("content", ""))
            self.refresh()

        elif msg_type == "reorder":
            container = self.query_one("#command_history")
            new_blocks_data = msg.get("blocks", [])
            new_ids = [b.get("id") for b in new_blocks_data]

            for b_id in list(self.blocks.keys()):
                if b_id not in new_ids:
                    self.blocks[b_id].remove()
                    del self.blocks[b_id]

            prev_widget = None
            for b_data in new_blocks_data:
                b_id = b_data.get("id")
                if b_id not in self.blocks:
                    await self.create_block(b_data)
                block = self.blocks[b_id]
                if prev_widget is not None:
                    container.move_child(block, after=prev_widget)
                prev_widget = block
            self.refresh()

        elif msg_type == "update_block":
            data = msg.get("block")
            if not data: return
            b_id = data.get("id")
            if b_id in self.blocks:
                block = self.blocks[b_id]
                if "content" in data:
                    block.content = data.get("content")
                if isinstance(block, CommandBlock):
                    old_status = getattr(block, "_last_status", None)
                    if "status" in data:
                        block._last_status = data.get("status")
                        block.update_status(data.get("status"))
                    if "cwd" in data:
                        block.cwd = data.get("cwd")
                    if "pty_uid" in data:
                        block.pty_uid = data.get("pty_uid")
                    if "pty_name" in data:
                        block.pty_name = data.get("pty_name")

                    if "pty_uid" in data or "pty_name" in data:
                         block.update_status(getattr(block, "_last_status", "ready"))

                    if "zoomed" in data:
                        if data["zoomed"] and not block.zoomed:
                            rows = data.get("zoom_rows", self.preferred_rows)
                            pty_rows = data.get("zoom_pty_rows", rows)
                            cols = data.get("zoom_cols", self.preferred_cols)
                            block.zoomed = True
                            block.styles.height = rows
                            block.query_one("#output").styles.height = pty_rows
                            block.query_one("#output").styles.max_height = pty_rows
                            block.add_class("-zoomed")
                            block.terminal_screen.resize(pty_rows, cols)
                            block.render_terminal()
                            block.scroll_visible()
                        elif not data["zoomed"] and block.zoomed:
                            rows, cols = self.preferred_rows, self.preferred_cols
                            block.zoomed = False
                            block.terminal_screen.resize(rows, cols)
                            block.styles.height = None
                            block.query_one("#output").styles.height = None
                            block.query_one("#output").styles.max_height = rows
                            block.remove_class("-zoomed")
                            block.render_terminal()
                            block.scroll_visible()

                    # Auto-exit CONTROL mode if block finishes
                    if self.input_mode == "CONTROL" and self.focused == block:
                        if old_status == "running" and data.get("status") != "running":
                            if self.was_in_selection_mode:
                                self.enter_selection_mode()
                            else:
                                self.enter_normal_mode()
                    if "output" in data:
                        block.output = ""
                        block.terminal_screen.reset()
                        block.append_output(data.get("output", ""))
                if not block.is_editing:
                   if isinstance(block, NoteBlock):
                       block.query_one("#md_render").update(block.content)
                       block.query_one("#block_text_edit").text = block.content
                   else:
                       block.update_header()
                       block.query_one("#block_text_edit").text = block.content

        elif msg_type == "output":
            b_id = msg.get("block_id")
            if b_id in self.blocks:
                self.blocks[b_id].append_output(msg.get("data"))

        elif msg_type == "lock":
            b_id = msg.get("block_id")
            if b_id in self.blocks:
                u_id, u_col, u_name = msg.get("user_id"), msg.get("user_color"), msg.get("user_name")
                self.users[u_id] = {"color": u_col, "name": u_name}
                self.blocks[b_id].update_lock(u_id, u_col)

        elif msg_type == "unlock":
            b_id = msg.get("block_id")
            if b_id in self.blocks:
                self.blocks[b_id].update_lock(None, None)

        elif msg_type == "remove_block":
            b_id = msg.get("block_id")
            if b_id in self.blocks:
                self.blocks[b_id].remove()
                del self.blocks[b_id]

        elif msg_type == "lock_denied":
            reason = msg.get("reason", "Block is locked")
            self.notify(reason, severity="warning")
            # If we were trying to enter edit mode, we should revert UI state
            b_id = msg.get("block_id")
            if b_id in self.blocks:
                block = self.blocks[b_id]
                if block.is_editing:
                    await block.toggle_edit(remote=True, restore=True)
            if self.input_mode == "CONTROL":
                if self.was_in_selection_mode:
                    self.enter_selection_mode()
                else:
                    self.enter_normal_mode()

        elif msg_type == "pty.created":
            uid = int(msg.get("uid"))
            pty_type = msg.get("pty_type")
            self.ptys[uid] = {"type": pty_type, "status": "idle", "block_count": 0, "name": msg.get("name")}
            if pty_type == "remote":
                self.last_remote_pty_uid = uid
            self.notify(f"PTY created: {msg.get('name')} (UID:{uid})")

        elif msg_type == "pty.destroyed":
            uid = int(msg.get("uid"))
            if uid in self.ptys:
                name = self.ptys[uid].get("name")
                del self.ptys[uid]
                self.notify(f"PTY destroyed: {name} (UID:{uid})")
            if self.default_pty_uid == uid:
                self.default_pty_uid = 0
                self.notify(f"Default PTY destroyed. Resetting to ID:0", severity="warning")
            if getattr(self, "current_pty_uid", None) == uid:
                self.current_pty_uid = 0

        elif msg_type == "pty.default_changed":
            # Handled client-side now
            pass

        elif msg_type == "pty.error":
            self.notify(f"PTY Error: {msg.get('message')}", severity="error")

        elif msg_type == "pty.list":
            server_ptys = msg.get("ptys", [])
            # Update local state from server list
            active_uids = []
            for p in server_ptys:
                uid = int(p.get("uid"))
                active_uids.append(uid)
                self.ptys[uid] = {
                    "type": p.get("type", "local"),
                    "status": p.get("status", "idle"),
                    "block_count": p.get("block_count", 0),
                    "active_block_id": p.get("active_block_id"),
                    "name": p.get("name")
                }
            # Remove ptys no longer on server
            for uid in list(self.ptys.keys()):
                if uid not in active_uids:
                    del self.ptys[uid]

            # Update PTY Manager if open
            for screen in self.screen_stack:
                if isinstance(screen, PTYManagerModal):
                    screen.ptys = self.ptys
                    screen.default_pty_uid = self.default_pty_uid
                    screen.update_list()

        elif msg_type == "queue_status":
            queues = msg.get("queues", [])
            for q in queues:
                uid = int(q.get("uid"))
                if uid in self.ptys:
                    self.ptys[uid]["block_count"] = q.get("block_count", 0)
                    if "status" in q:
                        self.ptys[uid]["status"] = q.get("status")
                    if "active_block_id" in q:
                        self.ptys[uid]["active_block_id"] = q.get("active_block_id")

            # Update PTY Manager if open
            for screen in self.screen_stack:
                if isinstance(screen, PTYManagerModal):
                    screen.update_list()

        elif msg_type == "autocomplete_response":
            rid = msg.get("request_id")
            results = msg.get("results", [])
            logging.debug(f"Client: Received autocomplete_response for RID {rid}, {len(results)} items")
            if rid in self._autocomplete_futures:
                logging.debug(f"Client: Setting future result for RID {rid}")
                self._autocomplete_futures[rid].set_result(results)
            else:
                logging.warning(f"Client: No future found for RID {rid}")

    async def create_block(self, data, is_editing=False, editing_content=None, cursor_pos=None):
        b_id = data.get("id")
        if not b_id or b_id in self.blocks: return
        b_type = data.get("type", "CMD")
        b_content = data.get("content", "")
        if b_type == "NOTE":
            new_block = NoteBlock(b_id, b_content, self, is_editing=is_editing, editing_content=editing_content, cursor_pos=cursor_pos)
        else:
            b_cwd = data.get("cwd", os.getcwd())
            b_pty_uid = data.get("pty_uid", 0)
            b_pty_name = data.get("pty_name", f"pty-{b_pty_uid}")
            new_block = CommandBlock(b_id, b_content, b_cwd, self, is_editing=is_editing, editing_content=editing_content, cursor_pos=cursor_pos, pty_uid=b_pty_uid, pty_name=b_pty_name)
        self.blocks[b_id] = new_block
        container = self.query_one("#command_history")
        await container.mount(new_block)

        if b_type == "CMD":
            new_block.append_output(data.get("output", ""))
            new_block.update_status(data.get("status", "ready"))
        locked_by = data.get("locked_by")
        if locked_by:
            user_info = self.users.get(locked_by, {})
            new_block.update_lock(locked_by, user_info.get("color", "white"))

        if data.get("zoomed") and isinstance(new_block, CommandBlock):
            rows = data.get("zoom_rows", self.preferred_rows)
            pty_rows = data.get("zoom_pty_rows", rows)
            cols = data.get("zoom_cols", self.preferred_cols)
            new_block.zoomed = True
            new_block.styles.height = rows
            new_block.query_one("#output").styles.height = pty_rows
            new_block.query_one("#output").styles.max_height = pty_rows
            new_block.add_class("-zoomed")
            new_block.terminal_screen.resize(pty_rows, cols)
            new_block.render_terminal()

        # Apply current filter to the new block
        inp = self.query_one("#filter_input")
        self._filter_single_block(new_block, inp.value)

        self.call_after_refresh(new_block.scroll_visible)

    def action_esc_pressed(self):
        bar = self.query_one("#filter_bar")
        inp = self.query_one("#filter_input")

        if not bar.has_class("hidden") and self.focused == inp:
            inp.value = self.previous_filter
            if not inp.value:
                bar.add_class("hidden")
            self.enter_normal_mode()
            return

        pty_bar = self.query_one("#pty_target_bar")
        pty_inp = self.query_one("#pty_target_input")
        if not pty_bar.has_class("hidden") and self.focused == pty_inp:
            pty_bar.add_class("hidden")
            self.enter_normal_mode()
            return

        if self.input_mode == "SELECTION":
            self.was_in_selection_mode = False
            self.enter_normal_mode()
        elif self.input_mode in ("BLOCKEDIT", "CONTROL", "BASH", "CMD", "NOTE"):
            if self.was_in_selection_mode:
                self.enter_selection_mode()
            else:
                self.enter_normal_mode()
        else:
            self.enter_normal_mode()

    def enter_normal_mode(self):
        if self.input_mode == "CONTROL":
            asyncio.create_task(self.send_message({"type": "control_stop"}))
        self.input_mode = "NORMAL"
        self.count_str = ""
        self.insert_after_id = None
        self.was_in_selection_mode = False
        self.update_mode_label()
        self.query_one("#mode_prefix").update("")
        self.query_one("#palette").remove_class("visible")
        self.query_one("#md_toolbox").hide()
        inp = self.query_one("#main_input")
        inp.text = ""
        inp.disabled = True
        # For non-interactive commands, trigger re-render to only show occupied space?
        for b in self.blocks.values():
             if isinstance(b, CommandBlock): b.render_terminal()
        try:
            self.query_one("#bottom_dock").focus()
        except:
            try: self.screen.focus()
            except: pass

    def enter_selection_mode(self):
        if self.input_mode == "CONTROL":
            asyncio.create_task(self.send_message({"type": "control_stop"}))
        self.input_mode = "SELECTION"
        self.update_mode_label()
        self.query_one("#main_input").disabled = True
        container = self.query_one("#command_history")
        blocks = [c for c in container.children if isinstance(c, BaseBlock) and not c.has_class("filtered-out")]
        if blocks:
            target = blocks[-1]
            if self.last_selected_block_id in self.blocks:
                target = self.blocks[self.last_selected_block_id]
            target.focus()
            target.scroll_visible()
            self.last_selected_block_id = target.block_id

    def enter_blockedit_mode(self):
        if self.input_mode == "SELECTION":
            self.was_in_selection_mode = True
        self.input_mode = "BLOCKEDIT"
        self.update_mode_label()
        self.query_one("#main_input").disabled = True

    def enter_input_mode(self, prefix="", pty_uid=None):
        if self.input_mode == "SELECTION":
            self.was_in_selection_mode = True
            focused = self.focused
            while focused and not isinstance(focused, BaseBlock):
                focused = focused.parent
            if focused:
                self.insert_after_id = focused.block_id
        elif self.input_mode == "INPUT" and self.was_in_selection_mode:
            # Keep existing insert_after_id set by !! or Picker flow
            pass
        elif not self.was_in_selection_mode:
            self.insert_after_id = None

        self.current_pty_uid = pty_uid if pty_uid is not None else self.default_pty_uid

        mode_map = {"!": "BASH", ":": "CMD", ";": "NOTE"}
        self.input_mode = mode_map.get(prefix, "INPUT")
        self.update_mode_label()
        pref_label = self.query_one("#mode_prefix")
        pref_label.update(prefix)
        colors = {"BASH": "#00e676", "CMD": "#2196f3", "NOTE": "#00b0ff"}
        pref_label.styles.color = colors.get(self.input_mode, "#2196f3")
        inp = self.query_one("#main_input")
        inp.disabled = False
        inp.language = "bash" if prefix in ("!", ":") else "markdown"
        inp.focus()

    def action_remove_filter(self):
        bar = self.query_one("#filter_bar")
        inp = self.query_one("#filter_input")
        bar.add_class("hidden")
        inp.value = ""
        for block in self.blocks.values():
            block.remove_class("filtered-out")
        if self.focused == inp:
            self.enter_normal_mode()

    def action_toggle_filter(self):
        bar = self.query_one("#filter_bar")
        inp = self.query_one("#filter_input")
        if bar.has_class("hidden") or self.focused != inp:
            self.previous_filter = inp.value
            bar.remove_class("hidden")
            inp.focus()
            self.input_mode = "INPUT"
            self.update_mode_label()
        else:
            bar.add_class("hidden")
            inp.value = ""
            for block in self.blocks.values(): block.remove_class("filtered-out")
            self.enter_normal_mode()

    @on(Input.Submitted, "#filter_input")
    def filter_submitted(self, event: Input.Submitted):
        if not event.value.strip():
            self.action_remove_filter()
        else:
            self.enter_normal_mode()

    @on(Input.Changed, "#filter_input")
    def filter_blocks(self, event: Input.Changed):
        self.apply_filter(event.value)

    def apply_filter(self, query: str):
        query = query.lower()
        for block in self.blocks.values():
            self._filter_single_block(block, query)

    def _filter_single_block(self, block, query: str):
        search_text = block.content + getattr(block, 'output', '')
        if fuzzy_match(query, search_text):
            block.remove_class("filtered-out")
        else:
            block.add_class("filtered-out")

    def update_mode_label(self):
        if not hasattr(self, "mode_label"): return
        colors = {
            "NORMAL": "#757575",
            "BASH": "#00e676",
            "CMD": "#7c4dff",
            "NOTE": "#ff5252",
            "SELECTION": "#00b0ff",
            "BLOCKEDIT": "#ffab40",
            "CONTROL": "#f44336"
        }
        c = colors.get(self.input_mode, "#7c4dff")
        text = f"[bold {c}]MODE: {self.input_mode}[/]"

        if self.input_mode == "BASH":
            uid = getattr(self, "current_pty_uid", self.default_pty_uid)
            info = self.ptys.get(uid, {})
            name = info.get("name", f"pty-{uid}")
            text += f" [cyan]➔ {name} (ID:{uid})[/]"

        self.mode_label.update(text)

    def enter_control_mode(self, block):
        if not isinstance(block, CommandBlock):
            return
        if self.input_mode == "SELECTION":
            self.was_in_selection_mode = True
        self.input_mode = "CONTROL"
        self.update_mode_label()
        self.query_one("#main_input").disabled = True
        block.focus()
        # Signal server to start streaming PTY output to this block
        asyncio.create_task(self.send_message({"type": "control_start", "block_id": block.block_id}))

    async def action_submit(self):
        try:
            ta = self.query_one("#main_input")
            text = ta.text
            if not text.strip():
                self.enter_normal_mode()
                return

            ta.text = ""
            self.query_one("#palette").remove_class("visible")
            self.query_one("#palette").styles.height = 0
            self.query_one("#md_toolbox").hide()

            target_pty_uid = getattr(self, "current_pty_uid", self.default_pty_uid)

            if self.input_mode == "CMD":
                await self.handle_internal_command(text.strip())
                if self.was_in_selection_mode:
                    self.enter_selection_mode()
                else:
                    self.enter_normal_mode()
                return

            if self.input_mode == "BASH":
                content = text.strip()
                logging.debug(f"Client: Submitting BASH command: '{content}' to UID {target_pty_uid}")
                self.history.add(content)

                if target_pty_uid not in self.ptys:
                    self.notify(f"Selected PTY (ID:{target_pty_uid}) no longer exists. Resetting to default.", severity="error")
                    self.default_pty_uid = 0
                    self.current_pty_uid = 0
                    self.action_spawn_pty_manager()
                    return

                # No longer intercepting 'cd' here; it will be handled by the server's master shell.
                await self.send_message({
                    "type": "submit",
                    "mode": "CMD",
                    "content": content,
                    "cwd": os.getcwd(),
                    "insert_after": self.insert_after_id,
                    "pty_uid": target_pty_uid
                })
            elif self.input_mode == "NOTE":
                await self.send_message({
                    "type": "submit",
                    "mode": "NOTE",
                    "content": text.strip(),
                    "cwd": os.getcwd(),
                    "insert_after": self.insert_after_id
                })

            if self.was_in_selection_mode:
                self.enter_selection_mode()
        except Exception as e:
            logging.exception(f"Error in action_submit: {e}")
            self.notify(f"Submit error: {e}", severity="error")
            self.enter_normal_mode()

    async def handle_internal_command(self, cmd_line):
        parts = cmd_line.split()
        if not parts: return
        cmd = parts[0]
        args = parts[1:]

        if cmd == "ptyman":
            self.action_spawn_pty_manager()
        elif cmd == "export":
            filename = args[0] if args else f"session_{int(time.time())}.md"
            include_output = "no-output" not in args
            self.export_notebook((filename, include_output))
        elif cmd == "import":
            if not args:
                self.notify("Usage: import <filename> [no-output]", severity="error")
                return
            filename = args[0]
            include_output = "no-output" not in args
            await self.import_notebook((filename, include_output))
        elif cmd == "exit": self.action_quit()
        elif cmd == "save_wf": self.action_save_workflow(self.query_one("#main_input").text)
        elif cmd == "clear": await self.send_message({"type": "clear_session"})
        elif cmd == "help": self.notify("Commands: pty [new|kill|list], spawnpty, export [file], import [file], exit, save_wf, clear, help")
        else: self.notify(f"Unknown command: {cmd}", severity="error")

    def action_change_pty(self):
        focused = self.focused
        while focused and not isinstance(focused, BaseBlock):
            focused = focused.parent

        if not focused and self.last_selected_block_id:
            focused = self.blocks.get(self.last_selected_block_id)

        if not focused or not isinstance(focused, CommandBlock):
            self.notify("no command block selected", severity="warning")
            return

        def _handle_change_result(res):
            if not res: return
            if res.get("action") == "select":
                uid = res.get("uid")
                focused.pty_uid = uid
                focused.pty_name = self.ptys.get(uid, {}).get("name", f"pty-{uid}")
                focused.update_header()
                focused.update_status(getattr(focused, "_last_status", "ready"))
                asyncio.create_task(self.send_message({
                    "type": "run_block",
                    "block_id": focused.block_id,
                    "pty_uid": uid,
                    "only_update": True # Hint to server to just update block without running
                }))

        self.push_screen(PTYManagerModal(self.ptys, self.default_pty_uid), _handle_change_result)

    def action_spawn_pty_manager(self):
        if self.input_mode == "SELECTION":
            self.was_in_selection_mode = True
            focused = self.focused
            while focused and not isinstance(focused, BaseBlock):
                focused = focused.parent
            if focused:
                self.insert_after_id = focused.block_id
        self.push_screen(PTYManagerModal(self.ptys, self.default_pty_uid), self._handle_manager_result)

    def _handle_manager_result(self, res):
        if not res: return
        action = res.get("action")
        if action == "select":
            uid = res.get("uid")
            self.default_pty_uid = uid
            self.enter_input_mode(prefix="!", pty_uid=uid)

    def _finish_remote_pty_create_callback(self, res):
        self.run_worker(self._finish_remote_pty_create("", "", res))

    def action_save_notebook_dialog(self): self.push_screen(SaveNotebookModal(), self.export_notebook)
    def action_import_notebook_dialog(self): self.push_screen(ImportNotebookModal(), lambda f: asyncio.create_task(self.import_notebook(f)))

    def action_save_workflow(self, text: str):
        if not text.strip(): return
        self.push_screen(SaveWorkflowModal(text.strip()), lambda s: s and asyncio.create_task(self._save_wf(s)))

    def action_save_workflow_from_input(self):
        self.action_save_workflow(self.query_one("#main_input").text)

    def action_clear_session(self):
        asyncio.create_task(self.send_message({"type": "clear_session"}))

    def _zoom_block(self, block: CommandBlock) -> None:
        container = self.query_one("#command_history")
        visible_height = container.size.height
        target_rows = max(self.preferred_rows, visible_height - 3)
        pty_rows = target_rows - 3
        target_cols = self.preferred_cols
        if pty_rows <= block.terminal_screen.lines:
            return
        block.zoomed = True
        block.styles.height = target_rows
        block.query_one("#output").styles.height = pty_rows
        block.query_one("#output").styles.max_height = pty_rows
        block.add_class("-zoomed")
        block.terminal_screen.resize(pty_rows, target_cols)
        asyncio.create_task(self.send_message({
            "type": "block_zoom",
            "block_id": block.block_id,
            "rows": target_rows,
            "cols": target_cols,
            "pty_rows": pty_rows,
        }))
        block.render_terminal()
        block.scroll_visible()

    def _unzoom_block(self, block: CommandBlock) -> None:
        rows, cols = self.preferred_rows, self.preferred_cols
        block.zoomed = False
        block.terminal_screen.resize(rows, cols)
        block.styles.height = None
        block.query_one("#output").styles.height = None
        block.query_one("#output").styles.max_height = rows
        block.remove_class("-zoomed")
        asyncio.create_task(self.send_message({
            "type": "block_unzoom",
            "block_id": block.block_id,
            "rows": rows,
            "cols": cols,
        }))
        block.render_terminal()
        block.scroll_visible()

    async def _rerun_block(self, block):
        if not isinstance(block, CommandBlock): return

        uid = block.pty_uid
        if uid is None or uid not in self.ptys:
            self.notify(f"Assigned PTY (ID:{uid}) no longer exists. Please select a new PTY.", severity="warning")
            def _handle_reassign(res):
                if res and res.get("action") == "select":
                    block.pty_uid = res.get("uid")
                    block.pty_name = self.ptys.get(block.pty_uid, {}).get("name", "unknown")
                    asyncio.create_task(self.send_message({"type": "run_block", "block_id": block.block_id, "pty_uid": block.pty_uid}))

            self.push_screen(PTYManagerModal(self.ptys, self.default_pty_uid), _handle_reassign)
            return

        await self.send_message({"type": "run_block", "block_id": block.block_id, "pty_uid": uid})

    def export_notebook(self, data):
        if not data: return
        filename, include_output = data if isinstance(data, tuple) else (data, True)
        if not filename: return
        md_output = [f"# Shell Notebook Export - {time.strftime('%Y-%m-%d %H:%M:%S')}\n"]

        # Iterate through visual children to respect current reordered state
        container = self.query_one("#command_history")
        for block in container.children:
            if isinstance(block, NoteBlock): md_output.append(f"{block.content}\n")
            elif isinstance(block, CommandBlock):
                pty_uid_export = block.pty_uid if block.pty_uid is not None else 0
                md_output.append(f"```bash (uid:{pty_uid_export})\n{block.content}\n```\n")
                if include_output and block.output:
                    clean = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', block.output)
                    if clean.strip():
                        # Use rstrip to keep leading indentation but remove trailing empty lines
                        md_output.append(f"```text\n{clean.rstrip()}\n```\n")
        try:
            with open(filename, "w") as f: f.write("\n".join(md_output))
            self.last_export_time = time.time()
            self.notify(f"Notebook Saved: {filename}", severity="information")
        except Exception as e: self.notify(f"Save Error: {e}", severity="error")

    async def import_notebook(self, data):
        if not data: return
        filename, include_output = data if isinstance(data, tuple) else (data, True)
        if not filename or not os.path.exists(filename): return
        try:
            with open(filename, "r") as f: content = f.read()
            pattern = re.compile(r'```(bash|text)(?:\s*\((.*?)\))?\n(.*?)\n```', re.DOTALL)
            last_pos, new_blocks = 0, []
            for match in pattern.finditer(content):
                before = content[last_pos:match.start()].strip()
                if before:
                    lines = [l for l in before.splitlines() if not l.strip().startswith("# Shell Notebook Export")]
                    if clean_before := "\n".join(lines).strip(): new_blocks.append({"type": "NOTE", "content": clean_before})
                lang, metadata, code = match.groups()
                if lang == "bash":
                    pty_uid = 0
                    if metadata and 'uid:' in metadata:
                        m = re.search(r'uid:(\d+)', metadata)
                        if m:
                            pty_uid = int(m.group(1))
                            if pty_uid != 0: pty_uid = None
                        else:
                            pty_uid = None # (uid:something) present but not int? default to none
                    else:
                        # No uid metadata at all
                        pty_uid = 0
                    new_blocks.append({"type": "CMD", "content": code, "cwd": os.getcwd(), "pty_uid": pty_uid})
                elif lang == "text" and include_output and new_blocks and new_blocks[-1]["type"] == "CMD":
                    # pyte expects \r\n for proper line breaks from a raw feed usually,
                    # but here we are restoring saved output.
                    # Normalize and ensure newlines are clean.
                    new_blocks[-1]["output"] = code.replace("\r\n", "\n").replace("\n", "\r\n")
                last_pos = match.end()
            if clean_after := "\n".join([l for l in content[last_pos:].splitlines() if not l.strip().startswith("# Shell Notebook Export")]).strip():
                new_blocks.append({"type": "NOTE", "content": clean_after})
            await self.send_message({"type": "import_blocks", "blocks": new_blocks})
            self.notify(f"Notebook Imported: {filename}", severity="information")
        except Exception as e: self.notify(f"Import Error: {e}", severity="error")

    async def action_move_up(self):
        if self.focused and isinstance(self.focused, BaseBlock): await self.send_message({"type": "move_block", "block_id": self.focused.block_id, "direction": "up"})
    async def action_move_down(self):
        if self.focused and isinstance(self.focused, BaseBlock): await self.send_message({"type": "move_block", "block_id": self.focused.block_id, "direction": "down"})
    async def action_delete_block(self):
        focused = self.focused
        while focused and not isinstance(focused, BaseBlock): focused = focused.parent
        if focused and isinstance(focused, BaseBlock):
            if focused.locked_by and focused.locked_by != self.user_id: self.notify(f"Locked by {self.focused.locked_by[:4]}", severity="warning"); return
            await self.send_message({"type": "delete_block", "block_id": focused.block_id})

    async def _save_wf(self, data):
        n, c = data; wfs = load_workflows(); wfs.append({"name": n, "cmd": c})
        with open(os.path.join(os.path.dirname(__file__), "termux_workflows.json"), "w") as f: json.dump(wfs, f, indent=4)
        self.workflows = load_workflows()

    @work(exclusive=True)
    async def update_palette(self, val: str):
        logging.debug(f"Client: update_palette called with val='{val}' len={len(val)} input_mode={self.input_mode}")
        try:
            p = self.query_one("#palette")
            spinner = self.query_one("#autocomplete_spinner")
        except: return
        self._last_suggestions = []
        if self.input_mode == "CONTROL":
             p.clear_options()
             p.remove_class("visible")
             p.styles.height = 0
             return

        provider = self.providers.get(self.input_mode)
        if not provider:
            p.clear_options()
            p.remove_class("visible"); return

        # Show and animate loading indicator
        spinner.remove_class("hidden")
        # Unicode spinner frames
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

        async def animate_spinner():
            i = 0
            while not spinner.has_class("hidden"):
                try:
                    spinner.update(frames[i % len(frames)])
                    i += 1
                    await asyncio.sleep(0.08)
                except asyncio.CancelledError:
                    break
                except:
                    break

        anim_task = asyncio.create_task(animate_spinner())

        context = {
            "app": self,
            "history": self.history.cache,
            "workflows": self.workflows,
            "cwd": os.getcwd(),
            "pty_uid": getattr(self, "current_pty_uid", self.default_pty_uid)
        }

        try:
            suggestions = await provider.get_suggestions(val, context)
            self._last_suggestions = suggestions
            logging.debug(f"Client: update_palette got {len(suggestions)} suggestions for input_mode={self.input_mode}")
            if suggestions:
                logging.debug(f"Client: First suggestion: {suggestions[0]}")
        finally:
            spinner.add_class("hidden")
            anim_task.cancel()

        p.clear_options()
        type_colors = {"shell": "green", "history": "yellow", "workflow": "cyan", "cmd": "bold magenta", "path": "green"}

        for s in suggestions:
            color = type_colors.get(s['type'], "white")
            display = escape(str(s.get('display', '')))
            desc = escape(str(s.get('description', '')))
            p.add_option(Option(f"[{color}]{s['type'].upper()}:[/] {display} [dim]{desc}[/]", id=f"{s['type']}___{s['value']}"))

        if p.option_count > 0:
            p.add_class("visible")
            if p.highlighted is None:
                p.highlighted = 0
            # Dynamic resizing of palette height (max 5 items)
            # Each item is roughly 1 line high.
            # Add 1 to account for border-bottom on .visible, so content isn't clipped.
            p.styles.height = min(p.option_count, 5) + 1
        else:
            p.remove_class("visible")
            p.styles.height = 0

    def sync_input(self):
        p = self.query_one("#palette")
        if p.highlighted is None: return
        opt = p.get_option_at_index(p.highlighted)
        raw_id = opt.id
        val = raw_id.split("___", 1)[1] if "___" in raw_id else raw_id
        inp = self.query_one("#main_input"); self._suppress_search = True

        if self.input_mode in ("BASH", "CMD"):
            provider = self.providers[self.input_mode]
            bash_prov = provider if self.input_mode == "BASH" else provider.bash_provider

            is_token_replace = False
            try:
                for s in self._last_suggestions:
                    if s.get("value") == val and s.get("type") in ("shell", "path"):
                        is_token_replace = True; break
            except: pass

            token = bash_prov._get_current_token(inp.text)
            if is_token_replace and token:
                idx = inp.text.rfind(token)
                inp.text = inp.text[:idx] + val
            elif is_token_replace and inp.text.endswith(" "):
                inp.text = inp.text + val
            else:
                inp.text = val
        else:
            inp.text = val
        inp.cursor_location = (len(inp.document.lines)-1, len(inp.document.lines[-1]))

    @on(OptionList.OptionSelected, "#palette")
    def opt_sel(self, event):
        self.sync_input()
        p = self.query_one("#palette")
        p.remove_class("visible")
        p.styles.height = 0
        self.query_one("#main_input").focus()
        if self.input_mode == "BASH":
            self.update_palette(self.query_one("#main_input").text)

    @on(MdElementSelected)
    def handle_md_selected(self, event: MdElementSelected):
        toolbox = self.query_one("#md_toolbox")
        toolbox.hide()
        inp = self.query_one("#main_input")

        sel = inp.selection
        sel_text = inp.selected_text if sel else ""
        has_sel = sel is not None and sel_text

        inp.focus()

        el = event.element
        val = el["value"]
        placeholder = el.get("placeholder")

        if has_sel:
            if placeholder and placeholder in val:
                wrapped = val.replace(placeholder, sel_text, 1)
            else:
                wrapped = val
            # Need to check which index is smaller to be independent of user selectiondirection
            start = inp.document.get_index_from_location(sel.start)
            end = inp.document.get_index_from_location(sel.end)
            first = min(start, end)
            last = max(start,end)
            inp.text = inp.text[:first] + wrapped + inp.text[last:]

        else:
            clean = val.replace(placeholder, "").strip() if placeholder else val
            inp.text = inp.text + clean

        self._suppress_search = True
        inp.cursor_location = (len(inp.document.lines)-1, len(inp.document.lines[-1]))

    @on(Input.Submitted, "#pty_target_input")
    async def pty_target_submitted(self, event: Input.Submitted):
        target = event.value.strip()
        self.query_one("#pty_target_bar").add_class("hidden")
        if not target:
            self.enter_normal_mode()
            return

        # Resolution order
        # 1. Exact UID match
        if target.isdigit():
            uid = int(target)
            if uid in self.ptys:
                self.enter_input_mode(prefix="!", pty_uid=uid)
                return

        # 2. Match by name
        for uid, info in self.ptys.items():
            if info.get("name") == target:
                self.enter_input_mode(prefix="!", pty_uid=uid)
                return

        # 3. "local" -> pty.create.local
        if target == "local":
            await self.send_message({"type": "pty.create.local"})
            # We don't have the UID yet, server will broadcast pty.created
            self.enter_input_mode(prefix="!")
            return

        # 4. user@host[:port][:key] -> remote
        if "@" in target:
            parts = target.split(":")
            user_host = parts[0]
            user, host = user_host.split("@", 1)
            port = "22"
            key_path = "~/.ssh/id_rsa"

            if len(parts) > 1:
                # Check if second part is a port or key path
                if parts[1].isdigit():
                    port = parts[1]
                    if len(parts) > 2:
                        key_path = parts[2]
                else:
                    key_path = parts[1]

            if len(parts) > 1: # Some extra info provided, maybe skip modal
                 # If only port was provided, we might still want the modal for key/password
                 # Unless it's user@host:port:key
                 if len(parts) > 2:
                     await self.send_message({
                         "type": "pty.create.remote",
                         "name": host,
                         "ssh_config": {"host": host, "user": user, "port": port, "key": key_path}
                     })
                     self.enter_input_mode(prefix="!")
                     return

            self.push_screen(RemotePTYAuthModal(host, user, port, key_path, host_history=self.remote_hosts),
                lambda res: self.run_worker(self._finish_remote_pty_create(host, user, res)))
            return

        self.notify(f"Unknown PTY target: {target}", severity="error")
        self.enter_normal_mode()

    async def _finish_remote_pty_create(self, host, user, res):
        if not res:
            self.enter_normal_mode()
            return

        h = res.get("host", host)
        u = res.get("user", user)

        entry = f"{u}@{h}"
        self._save_remote_host(entry)

        msg = {
            "type": "pty.create.remote",
            "name": None, # Let server generate unique name host-UID
            "ssh_config": {"host": h, "user": u, "port": res.get("port", "22")}
        }
        if res.get("method") == "key":
            msg["ssh_config"]["key"] = res.get("value")
        else:
            msg["ssh_config"]["password"] = res.get("value")

        await self.send_message(msg)
        self.enter_input_mode(prefix="!")

    def on_key(self, event: events.Key):
        # Allow Modals to handle their own keys (Tab, Esc, etc.) without interference
        if isinstance(self.screen, ModalScreen):
            return

        # Global exit hatch for CONTROL mode (failsafe)
        if self.input_mode == "CONTROL":
            # 1. Double Escape within 0.5s
            if event.key == "escape":
                now = time.time()
                if now - self.last_escape_time < 0.5:
                    self.action_esc_pressed()
                    event.stop(); event.prevent_default()
                    return
                self.last_escape_time = now

        if event.key == "escape" and self.input_mode != "CONTROL":
            toolbox = self.query_one("#md_toolbox")
            if toolbox.has_class("-visible"):
                toolbox.hide()
                self.query_one("#main_input").focus()
                event.prevent_default()
                return
            self.action_esc_pressed()
            return

        if event.key == "ctrl+g" and self.input_mode != "CONTROL":
            self.action_remove_filter()
            return

        p, inp = self.query_one("#palette"), self.query_one("#main_input")

        # Unified trigger handling for NORMAL and SELECTION
        if self.input_mode in ("NORMAL", "SELECTION"):
            if event.character == "!":
                now = time.time()
                if now - self.bang_time < 0.3:
                    # Double bang !!
                    self.bang_time = 0
                    if self.input_mode == "SELECTION":
                        self.was_in_selection_mode = True
                        focused = self.focused
                        while focused and not isinstance(focused, BaseBlock): focused = focused.parent
                        if focused: self.insert_after_id = focused.block_id

                    pty_bar = self.query_one("#pty_target_bar")
                    pty_bar.remove_class("hidden")
                    self.query_one("#pty_target_input").value = ""
                    self.query_one("#pty_target_input").focus()
                    self.input_mode = "INPUT"
                else:
                    self.bang_time = now
                    self._bang_uid_buffer = ""
                    async def delayed_bang(t):
                        await asyncio.sleep(0.3)
                        if self.bang_time == t:
                            self.bang_time = 0
                            self.enter_input_mode(prefix="!")
                    asyncio.create_task(delayed_bang(now))
                event.stop(); event.prevent_default(); return
            elif self.bang_time and event.character and event.character.isdigit():
                # Append digit to current bang_time buffer
                if not hasattr(self, "_bang_uid_buffer"): self._bang_uid_buffer = ""
                self._bang_uid_buffer += event.character
                # Restart delay for potentially more digits
                t_now = time.time()
                self.bang_time = t_now

                async def delayed_uid_finish(t):
                    await asyncio.sleep(0.4) # Slightly longer for multi-digit
                    if self.bang_time == t:
                        uid = int(self._bang_uid_buffer)
                        self._bang_uid_buffer = ""
                        self.bang_time = 0
                        if uid in self.ptys:
                            # Enter input mode for this UID without changing default
                            self.enter_input_mode(prefix="!", pty_uid=uid)
                        else:
                            self.notify(f"No PTY with UID {uid}", severity="error")
                asyncio.create_task(delayed_uid_finish(t_now))
                event.stop(); event.prevent_default(); return

        if self.input_mode == "NORMAL":
            if event.key == "ctrl+p":
                # Standard Command Palette (handled by Textual automatically if bound to ctrl+p by default,
                # but we override ctrl+p for PTYPicker before. Now we want it to be Command Palette)
                # Textual binds ctrl+p to CommandPalette by default on some versions,
                # let's just make sure it's triggered.
                self.action_command_palette()
                event.stop(); event.prevent_default(); return
            elif event.character == ":": self.enter_input_mode(prefix=":"); event.stop(); event.prevent_default()
            elif event.character == ";": self.enter_input_mode(prefix=";"); event.stop(); event.prevent_default()
            elif event.character == "s": self.enter_selection_mode(); event.stop(); event.prevent_default()
        elif self.input_mode in ("BASH", "CMD", "NOTE", "INPUT"):
            toolbox = self.query_one("#md_toolbox")

            if self.input_mode == "NOTE":
                tb_vis = toolbox.has_class("-visible")
                if tb_vis:
                    if event.key in ("up", "down"):
                        event.prevent_default()
                        ol = toolbox.query_one("#md_list")
                        idx = ol.highlighted if ol.highlighted is not None else 0
                        delta = -1 if event.key == "up" else 1
                        ol.highlighted = max(0, min(ol.option_count - 1, idx + delta))
                    elif event.key == "enter":
                        event.prevent_default()
                        ol = toolbox.query_one("#md_list")
                        if ol.highlighted is not None:
                            toolbox._select(ol.get_option_at_index(ol.highlighted).id)
                    elif event.key == "tab":
                        event.prevent_default()
                        ol = toolbox.query_one("#md_list")
                        if ol.highlighted is not None:
                            toolbox._select(ol.get_option_at_index(ol.highlighted).id)
                        else:
                            toolbox.hide()
                            self.query_one("#main_input").focus()
                    return
                elif event.key == "tab":
                    event.prevent_default()
                    toolbox.show()
                    return
                elif event.key == "ctrl+p" and self.query_one("#pty_target_bar").has_class("hidden"):
                    event.prevent_default()
                    toolbox.show()
                    return

            vis = p.has_class("visible")
            if event.key == "ctrl+p" and self.query_one("#pty_target_bar").has_class("hidden"):
                event.prevent_default()
                if vis:
                    p.remove_class("visible")
                    p.styles.height = 0
                else:
                    self.update_palette(inp.text)
            elif event.key in ("up", "down") and vis:
                event.prevent_default()
                p.highlighted = max(0, min(p.option_count-1, (p.highlighted or 0) + (-1 if event.key == "up" else 1)))
                self.sync_input()
            elif event.key == "tab":
                event.prevent_default()
                if not vis:
                    logging.debug(f"Client: tab pressed, inp.text={inp.text!r}, cursor={inp.cursor_location}")
                    self.update_palette(inp.text)
                else:
                    self.sync_input()
                    p.remove_class("visible")
                    p.styles.height = 0
        elif self.input_mode == "SELECTION":
            focused = self.focused; blocks = [c for c in self.query_one("#command_history").children if isinstance(c, BaseBlock) and not c.has_class("filtered-out")]
            if event.key == "ctrl+p":
                self.action_command_palette()
                event.stop(); event.prevent_default(); return
            if event.character and event.character.isdigit() and (event.character != "0" or self.count_str): self.count_str += event.character; return
            count, self.count_str = int(self.count_str) if self.count_str else 1, ""
            if event.character == ":": self.enter_input_mode(prefix=":"); return
            elif event.character == ";": self.enter_input_mode(prefix=";"); return
            if event.key in ("up", "down", "k", "j") and not (event.key in ("j", "enter") and isinstance(focused, CommandBlock) and not focused.is_editing):
                 if not blocks: return
                 idx = blocks.index(focused) if focused in blocks else -1
                 if event.key in ("down", "j"):
                    new_idx = min(len(blocks)-1, idx + count) if idx != -1 else 0
                 else:
                    new_idx = max(0, idx - count) if idx != -1 else len(blocks) - 1
                 blocks[new_idx].focus(); blocks[new_idx].scroll_visible()
                 self.last_selected_block_id = blocks[new_idx].block_id
            elif event.key == "x": asyncio.create_task(self.action_delete_block())
            elif event.key == "r": self.run_worker(self._rerun_block(focused))
            elif event.key == "c": self.action_change_pty()
            elif event.key == "y":
                 if isinstance(focused, NoteBlock): self.yank_buffer = ("NOTE", focused.content); self.notify("Note yanked")
                 elif isinstance(focused, CommandBlock): self.yank_buffer = ("CMD", focused.content, focused.cwd, focused.pty_uid); self.notify("Command yanked")
            elif event.key == "p":
                 if self.yank_buffer and focused in blocks: asyncio.create_task(self.send_message({"type": "paste_block", "target_id": focused.block_id, "position": "after", "yank_data": self.yank_buffer}))
            elif event.key == "P":
                 if self.yank_buffer and focused in blocks: asyncio.create_task(self.send_message({"type": "paste_block", "target_id": focused.block_id, "position": "before", "yank_data": self.yank_buffer}))
            elif event.key == "z" and isinstance(focused, CommandBlock):
                if focused.zoomed:
                    self._unzoom_block(focused)
                else:
                    self._zoom_block(focused)
            elif event.key == "e" and isinstance(focused, BaseBlock): asyncio.create_task(focused.toggle_edit())
            elif event.key == "ctrl+s" and isinstance(focused, CommandBlock): self.action_save_workflow(focused.content)
            elif event.key == "i" and isinstance(focused, CommandBlock): self.enter_control_mode(focused)
            elif event.key in ("j", "enter", "ctrl+j") and isinstance(focused, CommandBlock): self.run_worker(self._rerun_block(focused))
            elif event.key in ("ctrl+up", "alt+up"): asyncio.create_task(self.action_move_up())
            elif event.key in ("ctrl+down", "alt+down"): asyncio.create_task(self.action_move_down())
        elif self.input_mode == "CONTROL":
            focused = self.focused
            # Map common keys to ANSI sequences
            # Applications like 'less' often expect application mode sequences (ESC O A)
            # if they enable DECCKM. Standard mode is (ESC [ A).
            # We use a helper to check if DECCKM is enabled via pyte's mode set.
            # If DECCKM (Cursor Keys Mode) is enabled, we should send ESC O sequences
            # instead of ESC [ for arrow keys. This is often required by tools like 'less'.
            # In pyte, private modes are stored as (mode_number << 5) in the mode set.
            # DECCKM is Private Mode 1, so we check for (1 << 5) which is 32.
            app_mode = False
            if isinstance(focused, CommandBlock):
                app_mode = (1 << 5) in focused.terminal_screen.mode
            key_prefix = "\x1bO" if app_mode else "\x1b["

            key_map = {
                "enter": "\r",
                "backspace": "\x7f",
                "tab": "\t",
                "escape": "\x1b",
                "up": f"{key_prefix}A",
                "down": f"{key_prefix}B",
                "right": f"{key_prefix}C",
                "left": f"{key_prefix}D",
                "home": "\x1b[H",
                "end": "\x1b[F",
                "pageup": "\x1b[5~",
                "pagedown": "\x1b[6~",
                "delete": "\x1b[3~",
            }

            data = None
            if event.key in key_map:
                data = key_map[event.key]
            elif event.key == "ctrl+j": # Enter in selection mode or ctrl+j in some TUIs
                data = "\r"
            elif event.character:
                data = event.character
            elif len(event.key) == 1:
                data = event.key
            elif event.key.startswith("ctrl+"):
                char = event.key.split("+")[1]
                if len(char) == 1 and 'a' <= char.lower() <= 'z':
                    data = chr(ord(char.lower()) - ord('a') + 1)
                elif char == '[': # Ctrl+[ is common for Escape
                    data = "\x1b"

            if data:
                asyncio.create_task(self.send_message({"type": "terminal_input", "data": data}))
                event.stop()
                event.prevent_default()

    @on(TextArea.Changed, "#main_input")
    def in_ch(self, event):
        logging.debug(f"Client: TextArea.Changed text={event.text_area.text!r} cursor={event.text_area.cursor_location} suppress={self._suppress_search} palette_visible={self.query_one('#palette').has_class('visible')}")
        if not self._suppress_search and self.query_one("#palette").has_class("visible"): self.update_palette(event.text_area.text)
        self._suppress_search = False

    def on_click(self, event: events.Click):
        try:
            widget, _ = self.screen.get_widget_at(event.screen_x, event.screen_y)
            node = widget
            while node:
                if isinstance(node, BaseBlock):
                    if time.time() - node.last_click_time < 0.4:
                        self.query_one("#main_input").text = node.content; self.query_one("#main_input").focus()
                    else:
                        node.focus()
                        if node.is_editing: node.query_one("#block_text_edit").focus()
                    node.last_click_time = time.time(); return
                node = node.parent
        except: pass

    def on_paste(self, event: events.Paste) -> None:
        if self.input_mode == "CONTROL" and event.text:
            asyncio.create_task(self.send_message({"type": "terminal_input", "data": event.text}))
            event.stop()
            event.prevent_default()

    def _do_shutdown(self):
        self.exit()

    def on_unmount(self):
        self.history.save()
        if self.writer:
            try:
                msg = json.dumps({"type": "shutdown"}).encode() + b"\n"
                self.writer.write(msg)
            except:
                pass
            self.writer.close()

from branding import setup_parser

if __name__ == "__main__":
    parser = setup_parser("Neptune Client")
    parser.add_argument("-s", "--socket", default=DEFAULT_SOCKET_PATH, help="Path to the Unix Domain Socket")
    args = parser.parse_args()
    ClientApp(socket_path=args.socket).run()
