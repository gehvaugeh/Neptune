import os
import json
import asyncio
import re
import time
import argparse
import logging
import pyte
from typing import List, Dict

from rich.text import Text
from rich.style import Style
from rich.markup import escape
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, OptionList, Label, TextArea, Markdown, Button, Input
from textual.widgets.option_list import Option
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.binding import Binding
from textual.screen import ModalScreen
from textual import work, on, events, message

from common import HistoryManager, fuzzy_match, load_workflows, get_random_bright_color, THEME_FILE
from autocomplete import BashAutocompleteProvider, CmdAutocompleteProvider, MarkdownAutocompleteProvider

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

# --- MODALE DIALOGE ---

class SaveNotebookModal(ModalScreen):
    def compose(self) -> ComposeResult:
        with Vertical(id="modal_dialog"):
            yield Label("[bold cyan]Notebook exportieren (.md)[/]")
            yield Input(placeholder="dateiname.md", id="file_name", value=f"session_{int(time.time())}.md")
            with Horizontal(id="modal_buttons"):
                yield Button("Abbrechen", variant="error", id="cancel")
                yield Button("Exportieren", variant="success", id="export")
    @on(Button.Pressed, "#cancel")
    def cancel(self): self.dismiss(None)
    @on(Button.Pressed, "#export")
    def export(self):
        name = self.query_one("#file_name").value
        if not name.endswith(".md"): name += ".md"
        self.dismiss(name)

class ImportNotebookModal(ModalScreen):
    def compose(self) -> ComposeResult:
        with Vertical(id="modal_dialog"):
            yield Label("[bold magenta]Notebook importieren (.md)[/]")
            yield Input(placeholder="dateiname.md", id="file_name")
            with Horizontal(id="modal_buttons"):
                yield Button("Abbrechen", variant="error", id="cancel")
                yield Button("Importieren", variant="success", id="import")
    @on(Button.Pressed, "#cancel")
    def cancel(self): self.dismiss(None)
    @on(Button.Pressed, "#import")
    def import_nb(self):
        self.dismiss(self.query_one("#file_name").value)

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
            yield Label("[bold magenta]Save as Workflow[/]")
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
        yield Label("[dim]Note (esc: leave edit | ctrl+j: save)[/]", classes="block-info")

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
        elif event.key in ("ctrl+enter", "ctrl+j", "ctrl+m", "shift+enter"):
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
    def __init__(self, block_id, command, cwd, app_ref, is_editing=False, editing_content=None, cursor_pos=None, **kwargs):
        super().__init__(block_id, command, app_ref, is_editing, editing_content, cursor_pos, **kwargs)
        self.cwd = cwd
        self.full_output = ""
        # Initialize with fixed TTY dimensions established by the app
        self.terminal_screen = pyte.HistoryScreen(app_ref.preferred_cols, app_ref.preferred_rows, history=1000)
        self.stream = pyte.Stream(self.terminal_screen)
        self._style_cache = {}
        self._color_error = False
        self._last_status_text = "Ready"

    def compose(self) -> ComposeResult:
        label_classes = "" if not self.is_editing else "hidden"
        edit_classes = "" if self.is_editing else "hidden"

        with Horizontal(classes="block-header"):
            yield Label("➜", classes="prompt-symbol")
            yield Label(f"[bold blue]{escape(self.cwd)}[/]\n[white]{escape(self.content)}[/]", id="cmd_label", classes=label_classes)
            yield BlockEditor(self.editing_content, id="block_text_edit", classes=edit_classes, language="bash")
        yield Static("", id="output", classes="block-output", markup=False)
        yield Label("[grey44]Ready[/]", id="info", classes="block-info")

    def on_resize(self, event: events.Resize) -> None:
        # Fixed size TTY, no automatic resizing to match widget size
        pass

    def append_output(self, text: str):
        if not isinstance(text, str):
            text = text.decode(errors="replace")

        self.full_output += text
        if len(self.full_output) > 1_000_000:
            self.full_output = self.full_output[-1_000_000:]

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

    def update_status(self, status):
        if not self.is_mounted: return
        info = self.query_one("#info")
        if status == "running":
            self._last_status_text = "[yellow]Running...[/]"
            self.add_class("running")
        elif "queued" in status:
            num = status.split("(")[1].split(")")[0]
            self._last_status_text = f"[blue]⏳ In Queue (#{num})[/]"
            self.remove_class("running")
        elif status == "ok":
            self._last_status_text = "[green]✅ OK[/]"
            self.remove_class("running")
        elif "error" in status:
            self._last_status_text = f"[red]❌ {status.upper()}[/]"
            self.remove_class("running")
        else:
            self._last_status_text = f"[grey44]{status.capitalize()}[/]"

        if self._color_error:
            info.update(f"{self._last_status_text} [dim]⚠ color error[/]")
        else:
            info.update(self._last_status_text)

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

            label.update(f"[bold blue]{escape(self.cwd)}[/]\n[white]{escape(self.content)}[/]")
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

    def _on_mouse_event(self, event: events.MouseEvent) -> None:
        event.stop()
        event.prevent_default()

    BINDINGS = [
        Binding("ctrl+q", "quit", "Exit"),
        Binding("ctrl+f", "toggle_filter", "Filter"),
        Binding("escape", "esc_pressed", "Back/Clear")
    ]

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
        self._suppress_search = False
        self.workflows = load_workflows()
        self.yank_buffer = None
        self.last_selected_block_id = None
        self.was_in_selection_mode = False
        self.insert_after_id = None
        self.count_str = ""
        self.available_commands = [
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
            "NOTE": MarkdownAutocompleteProvider()
        }

    def compose(self) -> ComposeResult:
        with Horizontal(id="filter_bar", classes="hidden"):
            yield Label(" 🔍 Filter: ", id="filter_label")
            f_inp = Input(placeholder="Search blocks...", id="filter_input")
            f_inp.tooltip = "Enter text to filter blocks by command or output content."
            yield f_inp
        with ScrollableContainer(id="command_history"):
            yield Static("[bold #81d4fa]Neptune Multi-User | Collaborative Notebook[/]", id="notebook_header")
        with Vertical(id="bottom_dock") as dock:
            dock.can_focus = True
            yield OptionList(id="palette")
            self.mode_label = Label("[bold #757575]MODE: NORMAL[/]", id="mode_indicator")
            self.mode_label.tooltip = "Current interaction mode (NORMAL, BASH, CMD, NOTE, SELECTION, BLOCKEDIT)"
            yield self.mode_label
            with Horizontal(id="input_container"):
                yield Label("", id="mode_prefix")
                self.user_label = Label(f"User: [bold {self.user_color}]Me[/]", id="user_indicator")
                self.user_label.tooltip = "Your current username and unique color identifier."
                yield self.user_label
                m_inp = NotebookInput(language="bash", id="main_input")
                m_inp.tooltip = "Main command input. Use !, :, or ; in NORMAL mode to change input types."
                yield m_inp

    def on_mount(self):
        # Establish fixed TTY dimensions based on initial screen size
        # Margin for borders, padding, scrollbars and locking bars
        self.preferred_cols = max(40, self.screen.size.width - 10)
        self.preferred_rows = 24  # Standard fixed height for terminal blocks

        self.run_worker(self.connect_to_server())
        self.enter_normal_mode()

    def on_ready(self):
        # Focus screen or bottom dock to allow immediate use of prefix keys (! : ;)
        # We use call_after_refresh to ensure the layout is settled
        self.call_after_refresh(lambda: self.query_one("#bottom_dock").focus())

    async def connect_to_server(self):
        try:
            self.reader, self.writer = await asyncio.open_unix_connection(
                self.socket_path, limit=10 * 1024 * 1024
            )
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
        while self.reader and not self.reader.at_eof():
            try:
                line = await self.reader.readline()
                if not line: break
                try:
                    data = line.decode().strip()
                    if not data: continue
                    msg = json.loads(data)
                    self.post_message(ServerMessage(msg))
                except: continue
            except: break

    async def send_message(self, msg):
        if self.writer:
            try:
                self.writer.write(json.dumps(msg).encode() + b"\n")
                await self.writer.drain()
            except: pass

    async def on_server_message(self, event: ServerMessage):
        msg = event.data
        msg_type = msg.get("type")

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
                b_id = block_data["id"]
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
            await self.create_block(msg.get("block"))
            self.refresh()

        elif msg_type == "reorder":
            container = self.query_one("#command_history")
            new_blocks_data = msg.get("blocks", [])
            new_ids = [b["id"] for b in new_blocks_data]

            for b_id in list(self.blocks.keys()):
                if b_id not in new_ids:
                    self.blocks[b_id].remove()
                    del self.blocks[b_id]

            # Re-order logic while respecting the header
            header = container.query_one("#notebook_header")
            prev_widget = header
            for b_data in new_blocks_data:
                b_id = b_data["id"]
                if b_id not in self.blocks: await self.create_block(b_data)
                block = self.blocks[b_id]
                container.move_child(block, after=prev_widget)
                prev_widget = block
            self.refresh()

        elif msg_type == "update_block":
            data = msg.get("block")
            b_id = data["id"]
            if b_id in self.blocks:
                block = self.blocks[b_id]
                block.content = data["content"]
                if isinstance(block, CommandBlock):
                    old_status = getattr(block, "_last_status", None)
                    block._last_status = data["status"]
                    block.cwd = data["cwd"]
                    block.update_status(data["status"])

                    # Auto-exit CONTROL mode if block finishes
                    if self.input_mode == "CONTROL" and self.focused == block:
                        if old_status == "running" and data["status"] != "running":
                            if self.was_in_selection_mode:
                                self.enter_selection_mode()
                            else:
                                self.enter_normal_mode()
                    block.full_output = ""
                    block.terminal_screen.reset()
                    block.append_output(data.get("output", ""))
                if not block.is_editing:
                   if isinstance(block, NoteBlock):
                       block.query_one("#md_render").update(block.content)
                       block.query_one("#block_text_edit").text = block.content
                   else:
                       block.query_one("#cmd_label").update(f"[bold blue]{escape(block.cwd)}[/]\n[white]{escape(block.content)}[/]")
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
                self.enter_normal_mode()

    async def create_block(self, data, is_editing=False, editing_content=None, cursor_pos=None):
        b_id = data["id"]
        if b_id in self.blocks: return
        if data["type"] == "NOTE": new_block = NoteBlock(b_id, data["content"], self, is_editing=is_editing, editing_content=editing_content, cursor_pos=cursor_pos)
        else:
            new_block = CommandBlock(b_id, data["content"], data["cwd"], self, is_editing=is_editing, editing_content=editing_content, cursor_pos=cursor_pos)
        self.blocks[b_id] = new_block
        container = self.query_one("#command_history")
        await container.mount(new_block)

        if data["type"] == "CMD":
            new_block.append_output(data["output"])
            new_block.update_status(data["status"])
        if data["locked_by"]:
                user_info = self.users.get(data["locked_by"], {})
                new_block.update_lock(data["locked_by"], user_info.get("color", "white"))
        self.call_after_refresh(new_block.scroll_visible)

    def action_esc_pressed(self):
        bar = self.query_one("#filter_bar")
        if not bar.has_class("hidden"):
            self.action_toggle_filter()
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
        inp = self.query_one("#main_input")
        inp.text = ""
        inp.disabled = True
        # For non-interactive commands, trigger re-render to only show occupied space?
        for b in self.blocks.values():
             if isinstance(b, CommandBlock): b.render_terminal()
        try:
            self.screen.focus()
        except: pass

    def enter_selection_mode(self):
        self.input_mode = "SELECTION"
        self.update_mode_label()
        self.query_one("#main_input").disabled = True
        container = self.query_one("#command_history")
        blocks = [c for c in container.children if isinstance(c, BaseBlock)]
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

    def enter_input_mode(self, prefix=""):
        if self.input_mode == "SELECTION":
            self.was_in_selection_mode = True
            focused = self.focused
            while focused and not isinstance(focused, BaseBlock):
                focused = focused.parent
            if focused:
                self.insert_after_id = focused.block_id
        else:
            self.insert_after_id = None

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

    def action_toggle_filter(self):
        bar = self.query_one("#filter_bar")
        if bar.has_class("hidden"):
            bar.remove_class("hidden")
            self.query_one("#filter_input").focus()
            self.input_mode = "INPUT"
            self.update_mode_label()
        else:
            bar.add_class("hidden")
            self.query_one("#filter_input").value = ""
            for block in self.blocks.values(): block.remove_class("filtered-out")
            self.enter_normal_mode()

    @on(Input.Changed, "#filter_input")
    def filter_blocks(self, event: Input.Changed):
        query = event.value.lower()
        for block in self.blocks.values():
            search_text = (block.content + block.full_output).lower() if isinstance(block, CommandBlock) else block.content.lower()
            if not query or query in search_text: block.remove_class("filtered-out")
            else: block.add_class("filtered-out")

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
        self.mode_label.update(f"[bold {c}]MODE: {self.input_mode}[/]")

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
        ta = self.query_one("#main_input"); text = ta.text
        if not text.strip(): self.enter_normal_mode(); return
        ta.text = ""; self.query_one("#palette").remove_class("visible")

        if self.input_mode == "CMD":
            await self.handle_internal_command(text.strip())
            if self.was_in_selection_mode:
                self.enter_selection_mode()
            else:
                self.enter_normal_mode()
            return

        if self.input_mode == "BASH":
            content = text.strip()
            self.history.add(content)
            # No longer intercepting 'cd' here; it will be handled by the server's master shell.
            await self.send_message({
                "type": "submit",
                "mode": "CMD",
                "content": content,
                "cwd": os.getcwd(),
                "insert_after": self.insert_after_id
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
        else:
            self.enter_normal_mode()

    async def handle_internal_command(self, cmd_line):
        parts = cmd_line.split(" ", 1)
        cmd, args = parts[0], parts[1] if len(parts) > 1 else ""
        if cmd == "export": self.export_notebook(args or f"session_{int(time.time())}.md")
        elif cmd == "import": await self.import_notebook(args)
        elif cmd == "exit": self.exit()
        elif cmd == "save_wf": self.action_save_workflow(self.query_one("#main_input").text)
        elif cmd == "clear": await self.send_message({"type": "clear_session"})
        elif cmd == "help": self.notify("Commands: export [file], import [file], exit, save_wf, clear, help")
        else: self.notify(f"Unknown command: {cmd}", severity="error")

    def action_save_notebook_dialog(self): self.push_screen(SaveNotebookModal(), self.export_notebook)
    def action_import_notebook_dialog(self): self.push_screen(ImportNotebookModal(), lambda f: asyncio.create_task(self.import_notebook(f)))

    def action_save_workflow(self, text: str):
        if not text.strip(): return
        self.push_screen(SaveWorkflowModal(text.strip()), lambda s: s and asyncio.create_task(self._save_wf(s)))

    def export_notebook(self, filename: str):
        if not filename: return
        md_output = [f"# Shell Notebook Export - {time.strftime('%Y-%m-%d %H:%M:%S')}\n"]

        # Iterate through visual children to respect current reordered state
        container = self.query_one("#command_history")
        for block in container.children:
            if isinstance(block, NoteBlock): md_output.append(f"{block.content}\n")
            elif isinstance(block, CommandBlock):
                md_output.append(f"```bash\n{block.content}\n```\n")
                if block.full_output.strip():
                    clean = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', block.full_output)
                    md_output.append(f"```text\n{clean.strip()}\n```\n")
        try:
            with open(filename, "w") as f: f.write("\n".join(md_output))
            self.notify(f"Notebook Saved: {filename}", severity="information")
        except Exception as e: self.notify(f"Save Error: {e}", severity="error")

    async def import_notebook(self, filename: str):
        if not filename or not os.path.exists(filename): return
        try:
            with open(filename, "r") as f: content = f.read()
            pattern = re.compile(r'```(bash|text)\n(.*?)\n```', re.DOTALL)
            last_pos, new_blocks = 0, []
            for match in pattern.finditer(content):
                before = content[last_pos:match.start()].strip()
                if before:
                    lines = [l for l in before.splitlines() if not l.strip().startswith("# Shell Notebook Export")]
                    if clean_before := "\n".join(lines).strip(): new_blocks.append({"type": "NOTE", "content": clean_before})
                lang, code = match.groups()
                if lang == "bash": new_blocks.append({"type": "CMD", "content": code, "cwd": os.getcwd()})
                elif lang == "text" and new_blocks and new_blocks[-1]["type"] == "CMD": new_blocks[-1]["output"] = code
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

    def _get_current_token(self, text: str) -> str:
        if not text or text.endswith(" "): return ""
        parts = re.findall(r'(?:[^\s"\']|"(?:\\.|[^"])*"|\'(?:\\.|[^\'])*\')+', text)
        return parts[-1] if parts else ""

    def update_palette(self, val: str):
        p = self.query_one("#palette"); p.clear_options()
        provider = self.providers.get(self.input_mode)
        if not provider:
            p.remove_class("visible"); return

        context = {
            "history": self.history.cache,
            "workflows": self.workflows,
            "cwd": os.getcwd()
        }
        suggestions = provider.get_suggestions(val, context)

        type_colors = {"path": "green", "history": "yellow", "workflow": "cyan", "cmd": "bold magenta", "md": "bold #ff5252"}

        for s in suggestions:
            color = type_colors.get(s['type'], "white")
            p.add_option(Option(f"[{color}]{s['type'].upper()}:[/] {s['display']} [dim]{s['description']}[/]", id=s['value']))

        if p.option_count > 0: p.add_class("visible")
        else: p.remove_class("visible")

    def sync_input(self):
        p = self.query_one("#palette")
        if p.highlighted is None: return
        opt = p.get_option_at_index(p.highlighted)
        val = opt.id
        inp = self.query_one("#main_input"); self._suppress_search = True

        if self.input_mode in ("BASH", "CMD"):
            provider = self.providers[self.input_mode]
            bash_prov = provider if self.input_mode == "BASH" else provider.bash_provider

            # Check if selection is a path. Path completion uses token replacement.
            # History, Workflow, and Cmd types use full replacement.
            is_path = False
            try:
                # Retrieve the actual suggestion object to check its type
                context = {"history": self.history.cache, "workflows": self.workflows, "cwd": os.getcwd()}
                sugs = provider.get_suggestions(inp.text, context)
                for s in sugs:
                    if s["value"] == val and s["type"] == "path":
                        is_path = True; break
            except: pass

            token = bash_prov._get_current_token(inp.text)
            if is_path and token:
                idx = inp.text.rfind(token)
                inp.text = inp.text[:idx] + val
            else:
                inp.text = val # Full replacement for history/workflows
        else:
            inp.text = val
        inp.cursor_location = (len(inp.document.lines)-1, len(inp.document.lines[-1]))

    @on(OptionList.OptionSelected, "#palette")
    def opt_sel(self, event):
        self.sync_input()
        self.query_one("#palette").remove_class("visible")
        self.query_one("#main_input").focus()
        if self.input_mode == "BASH":
            self.update_palette(self.query_one("#main_input").text)

    def on_key(self, event: events.Key):
        if event.key == "escape":
            self.action_esc_pressed()
            return
        p, inp = self.query_one("#palette"), self.query_one("#main_input")
        if self.input_mode == "NORMAL":
            if event.character == "!": self.enter_input_mode(prefix="!"); event.stop(); event.prevent_default()
            elif event.character == ":": self.enter_input_mode(prefix=":"); event.stop(); event.prevent_default()
            elif event.character == ";": self.enter_input_mode(prefix=";"); event.stop(); event.prevent_default()
            elif event.character == "s": self.enter_selection_mode(); event.stop(); event.prevent_default()
        elif self.input_mode in ("BASH", "CMD", "NOTE", "INPUT"):
            vis = p.has_class("visible")
            if event.key == "ctrl+p":
                event.prevent_default()
                if vis: p.remove_class("visible")
                else: p.add_class("visible"); self.update_palette(inp.text)
            elif event.key in ("up", "down") and vis:
                event.prevent_default(); p.highlighted = max(0, min(p.option_count-1, (p.highlighted or 0) + (-1 if event.key == "up" else 1))); self.sync_input()
            elif event.key == "tab":
                event.prevent_default()
                if not vis: p.add_class("visible"); self.update_palette(inp.text)
                else: self.sync_input(); p.remove_class("visible")
        elif self.input_mode == "SELECTION":
            focused = self.focused; blocks = [c for c in self.query_one("#command_history").children if isinstance(c, BaseBlock)]
            if event.character and event.character.isdigit() and (event.character != "0" or self.count_str): self.count_str += event.character; return
            count, self.count_str = int(self.count_str) if self.count_str else 1, ""
            if event.character in (":", "!", ";"): self.enter_input_mode(prefix=event.character); return
            if event.key in ("up", "down", "k", "j") and not (event.key in ("j", "enter") and isinstance(focused, CommandBlock) and not focused.is_editing):
                 if not blocks: return
                 idx = blocks.index(focused) if focused in blocks else 0
                 new_idx = max(0, min(len(blocks)-1, idx + (count if event.key in ("down", "j") else -count)))
                 blocks[new_idx].focus(); blocks[new_idx].scroll_visible()
                 self.last_selected_block_id = blocks[new_idx].block_id
            elif event.key == "x": asyncio.create_task(self.action_delete_block())
            elif event.key == "r": asyncio.create_task(self.send_message({"type": "run_block", "block_id": focused.block_id}))
            elif event.key == "y":
                 if isinstance(focused, NoteBlock): self.yank_buffer = ("NOTE", focused.content); self.notify("Note yanked")
                 elif isinstance(focused, CommandBlock): self.yank_buffer = ("CMD", focused.content, focused.cwd); self.notify("Command yanked")
            elif event.key == "p":
                 if self.yank_buffer and focused in blocks: asyncio.create_task(self.send_message({"type": "paste_block", "target_id": focused.block_id, "position": "after", "yank_data": self.yank_buffer}))
            elif event.key == "P":
                 if self.yank_buffer and focused in blocks: asyncio.create_task(self.send_message({"type": "paste_block", "target_id": focused.block_id, "position": "before", "yank_data": self.yank_buffer}))
            elif event.key == "e" and isinstance(focused, BaseBlock): asyncio.create_task(focused.toggle_edit())
            elif event.key == "ctrl+s" and isinstance(focused, CommandBlock): self.action_save_workflow(focused.content)
            elif event.key == "i" and isinstance(focused, CommandBlock): self.enter_control_mode(focused)
            elif event.key in ("j", "enter", "ctrl+j") and isinstance(focused, CommandBlock): asyncio.create_task(self.send_message({"type": "run_block", "block_id": focused.block_id}))
            elif event.key in ("ctrl+up", "alt+up"): asyncio.create_task(self.action_move_up())
            elif event.key in ("ctrl+down", "alt+down"): asyncio.create_task(self.action_move_down())
        elif self.input_mode == "CONTROL":
            focused = self.focused
            if event.key == "ctrl+escape":
                self.enter_normal_mode()
                return

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

    def on_unmount(self):
        if self.writer: self.writer.close()
        self.history.save()

from branding import setup_parser

if __name__ == "__main__":
    parser = setup_parser("Neptune Client")
    parser.add_argument("-s", "--socket", default=DEFAULT_SOCKET_PATH, help="Path to the Unix Domain Socket")
    args = parser.parse_args()
    ClientApp(socket_path=args.socket).run()
