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

DEFAULT_SOCKET_PATH = "/tmp/gemmi_shell.sock"

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

    def on_mount(self) -> None:
        if self.is_editing and self.cursor_pos:
            edit = self.query_one("#block_text_edit")
            edit.cursor_location = self.cursor_pos

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
                self.app_ref.enter_normal_mode()

class NotebookInput(TextArea):
    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            asyncio.create_task(self.app.action_submit())
        elif event.key in ("ctrl+enter", "ctrl+j", "ctrl+m"):
            event.stop()
            event.prevent_default()
            self.insert("\n")
        elif event.key == "escape":
            event.stop()
            event.prevent_default()
            self.app.enter_normal_mode()

class CommandBlock(BaseBlock):
    def __init__(self, block_id, command, cwd, app_ref, is_editing=False, editing_content=None, cursor_pos=None, **kwargs):
        super().__init__(block_id, command, app_ref, is_editing, editing_content, cursor_pos, **kwargs)
        self.cwd = cwd
        self.full_output = ""
        self.terminal_screen = pyte.Screen(80, 24)
        self.stream = pyte.Stream(self.terminal_screen)

    def compose(self) -> ComposeResult:
        label_classes = "" if not self.is_editing else "hidden"
        edit_classes = "" if self.is_editing else "hidden"

        with Horizontal(classes="block-header"):
            yield Label("➜", classes="prompt-symbol")
            yield Label(f"[bold blue]{self.cwd}[/]\n[white]{self.content}[/]", id="cmd_label", classes=label_classes)
            yield BlockEditor(self.editing_content, id="block_text_edit", classes=edit_classes, language="bash")
        yield Static("", id="output", classes="block-output", markup=False)
        yield Label("[grey44]Ready[/]", id="info", classes="block-info")

    def append_output(self, text: str):
        if not isinstance(text, str):
            text = text.decode(errors="replace")

        self.full_output += text
        if len(self.full_output) > 1_000_000:
            self.full_output = self.full_output[-1_000_000:]

        self.stream.feed(text)

        # If we are in CONTROL mode, use the terminal screen rendering
        if self.app_ref.input_mode == "CONTROL" and self.app_ref.focused == self:
            screen_text = "\n".join(line.rstrip() for line in self.terminal_screen.display)
            self.query_one("#output").update(Text(screen_text))
        else:
            # For regular command blocks, use the scrolling ANSI output
            self.query_one("#output").update(Text.from_ansi(self.full_output))

    def update_status(self, status):
        info = self.query_one("#info")
        if status == "running":
            info.update("[yellow]Running...[/]")
            self.add_class("running")
        elif status == "ok":
            info.update("[green]✅ OK[/]")
            self.remove_class("running")
        elif "error" in status:
            info.update(f"[red]❌ {status.upper()}[/]")
            self.remove_class("running")

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

            label.update(f"[bold blue]{self.cwd}[/]\n[white]{self.content}[/]")
            label.remove_class("hidden")
            edit.add_class("hidden")
            if not remote:
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
        self.count_str = ""
        self.available_commands = [
            {"name": "export", "params": "[file]", "desc": "Export notebook to Markdown"},
            {"name": "import", "params": "[file]", "desc": "Import notebook from Markdown"},
            {"name": "exit", "params": "", "desc": "Exit Gemmi-Shell"},
            {"name": "save_wf", "params": "", "desc": "Save current input as Workflow"},
            {"name": "help", "params": "", "desc": "Show help message"},
            {"name": "clear", "params": "", "desc": "Clear all blocks and shell state"},
        ]
        self.providers = {
            "BASH": BashAutocompleteProvider(),
            "CMD": CmdAutocompleteProvider(self.available_commands),
            "NOTE": MarkdownAutocompleteProvider()
        }

    def compose(self) -> ComposeResult:
        with Horizontal(id="filter_bar", classes="hidden"):
            yield Label(" 🔍 Filter: ", id="filter_label")
            yield Input(placeholder="Search blocks...", id="filter_input")
        with ScrollableContainer(id="command_history"):
            yield Static("[bold magenta]Gemmi-Shell Multi-User | Collaborative Notebook[/]")
        with Vertical(id="bottom_dock"):
            yield OptionList(id="palette")
            self.mode_label = Label("[bold #757575]MODE: NORMAL[/]", id="mode_indicator")
            yield self.mode_label
            with Horizontal(id="input_container"):
                yield Label("", id="mode_prefix")
                self.user_label = Label(f"User: [bold {self.user_color}]Me[/]", id="user_indicator")
                yield self.user_label
                yield NotebookInput(language="bash", id="main_input")

    def on_mount(self):
        self.run_worker(self.connect_to_server())
        self.enter_normal_mode()

    def on_ready(self):
        self.query_one("#main_input").focus()

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

            for i, b_data in enumerate(new_blocks_data):
                b_id = b_data["id"]
                if b_id not in self.blocks: await self.create_block(b_data)
                block = self.blocks[b_id]
                if i == 0:
                    if container.children and container.children[0] != block: container.move_child(block, before=container.children[0])
                else:
                    prev_id = new_blocks_data[i-1]["id"]
                    if prev_id in self.blocks: container.move_child(block, after=self.blocks[prev_id])
            self.refresh()

        elif msg_type == "update_block":
            data = msg.get("block")
            b_id = data["id"]
            if b_id in self.blocks:
                block = self.blocks[b_id]
                block.content = data["content"]
                if isinstance(block, CommandBlock):
                    block.cwd = data["cwd"]
                    block.update_status(data["status"])
                    block.full_output = data.get("output", "")
                    block.query_one("#output").update(Text.from_ansi(block.full_output))
                if not block.is_editing:
                   if isinstance(block, NoteBlock):
                       block.query_one("#md_render").update(block.content)
                       block.query_one("#block_text_edit").text = block.content
                   else:
                       block.query_one("#cmd_label").update(f"[bold blue]{block.cwd}[/]\n[white]{block.content}[/]")
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

    async def create_block(self, data, is_editing=False, editing_content=None, cursor_pos=None):
        b_id = data["id"]
        if b_id in self.blocks: return
        if data["type"] == "NOTE": new_block = NoteBlock(b_id, data["content"], self, is_editing=is_editing, editing_content=editing_content, cursor_pos=cursor_pos)
        else:
            new_block = CommandBlock(b_id, data["content"], data["cwd"], self, is_editing=is_editing, editing_content=editing_content, cursor_pos=cursor_pos)
            new_block.full_output = data["output"]
        self.blocks[b_id] = new_block
        container = self.query_one("#command_history")
        await container.mount(new_block)
        if data["type"] == "CMD":
            new_block.update_status(data["status"])
            if data["output"]: new_block.query_one("#output").update(Text.from_ansi(data["output"]))
        if data["locked_by"]:
                user_info = self.users.get(data["locked_by"], {})
                new_block.update_lock(data["locked_by"], user_info.get("color", "white"))
        self.call_after_refresh(new_block.scroll_visible)

    def action_esc_pressed(self):
        bar = self.query_one("#filter_bar")
        if not bar.has_class("hidden"): self.action_toggle_filter()
        self.enter_normal_mode()

    def enter_normal_mode(self):
        self.input_mode = "NORMAL"
        self.count_str = ""
        self.update_mode_label()
        self.query_one("#mode_prefix").update("")
        self.query_one("#palette").remove_class("visible")
        inp = self.query_one("#main_input")
        inp.text = ""
        inp.disabled = True
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
            blocks[-1].focus()
            blocks[-1].scroll_visible()

    def enter_blockedit_mode(self):
        self.input_mode = "BLOCKEDIT"
        self.update_mode_label()
        self.query_one("#main_input").disabled = True

    def enter_input_mode(self, prefix=""):
        mode_map = {"!": "BASH", ":": "CMD", ";": "NOTE"}
        self.input_mode = mode_map.get(prefix, "INPUT")
        self.update_mode_label()
        pref_label = self.query_one("#mode_prefix")
        pref_label.update(prefix)
        colors = {"BASH": "#00e676", "CMD": "#7c4dff", "NOTE": "#ff5252"}
        pref_label.styles.color = colors.get(self.input_mode, "#7c4dff")
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
        self.input_mode = "CONTROL"
        self.update_mode_label()
        self.query_one("#main_input").disabled = True
        block.focus()
        # Request terminal resize to match block width
        try:
            # Approximate size based on widget size
            cols = block.size.width - 4 # minus padding/border
            rows = 24 # Default rows
            asyncio.create_task(self.send_message({"type": "terminal_resize", "rows": rows, "cols": cols}))
        except: pass

    async def action_submit(self):
        ta = self.query_one("#main_input"); text = ta.text
        if not text.strip(): self.enter_normal_mode(); return
        ta.text = ""; self.query_one("#palette").remove_class("visible")

        if self.input_mode == "CMD":
            await self.handle_internal_command(text.strip())
            self.enter_normal_mode()
            return

        if self.input_mode == "BASH":
            content = text.strip()
            self.history.add(content)
            await self.send_message({"type": "submit", "mode": "CMD", "content": content, "cwd": os.getcwd()})
        elif self.input_mode == "NOTE":
            await self.send_message({"type": "submit", "mode": "NOTE", "content": text.strip(), "cwd": os.getcwd()})

        self.enter_normal_mode()

    async def handle_internal_command(self, cmd_line):
        parts = cmd_line.split(" ", 1)
        cmd, args = parts[0], parts[1] if len(parts) > 1 else ""
        if cmd == "export": self.export_notebook(args or f"session_{int(time.time())}.md")
        elif cmd == "import": await self.import_notebook(args)
        elif cmd == "exit": self.exit()
        elif cmd == "save_wf": self.action_save_wf_dialog()
        elif cmd == "clear": await self.send_message({"type": "clear_session"})
        elif cmd == "help": self.notify("Commands: export [file], import [file], exit, save_wf, clear, help")
        else: self.notify(f"Unknown command: {cmd}", severity="error")

    def action_save_notebook_dialog(self): self.push_screen(SaveNotebookModal(), self.export_notebook)
    def action_import_notebook_dialog(self): self.push_screen(ImportNotebookModal(), lambda f: asyncio.create_task(self.import_notebook(f)))

    def export_notebook(self, filename: str):
        if not filename: return
        md_output = [f"# Shell Notebook Export - {time.strftime('%Y-%m-%d %H:%M:%S')}\n"]
        for block in self.blocks.values():
            if isinstance(block, NoteBlock): md_output.append(f"{block.content}\n")
            elif isinstance(block, CommandBlock):
                md_output.append(f"```bash\n{block.content}\n```\n")
                if block.full_output.strip():
                    clean = re.sub(r'\x1B[@-_][0-?]*[ -/]*[@-~]', '', block.full_output)
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

    def action_save_wf_dialog(self):
        self.push_screen(SaveWorkflowModal(self.query_one("#main_input").text), lambda s: s and asyncio.create_task(self._save_wf(s)))
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

        if self.input_mode == "BASH":
            token = self.providers["BASH"]._get_current_token(inp.text)
            if token:
                idx = inp.text.rfind(token)
                inp.text = inp.text[:idx] + val
            else:
                inp.text += val
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
        if event.key == "escape": self.enter_normal_mode(); return
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
            if event.key in ("up", "down", "k", "j") and not (event.key == "j" and isinstance(focused, CommandBlock) and not focused.is_editing):
                 if not blocks: return
                 idx = blocks.index(focused) if focused in blocks else 0
                 new_idx = max(0, min(len(blocks)-1, idx + (count if event.key in ("down", "j") else -count)))
                 blocks[new_idx].focus(); blocks[new_idx].scroll_visible()
            elif event.key == "x": asyncio.create_task(self.action_delete_block())
            elif event.key == "y":
                 if isinstance(focused, NoteBlock): self.yank_buffer = ("NOTE", focused.content); self.notify("Note yanked")
                 elif isinstance(focused, CommandBlock): self.yank_buffer = ("CMD", focused.content, focused.cwd); self.notify("Command yanked")
            elif event.key == "p":
                 if self.yank_buffer and focused in blocks: asyncio.create_task(self.send_message({"type": "paste_block", "target_id": focused.block_id, "position": "after", "yank_data": self.yank_buffer}))
            elif event.key == "P":
                 if self.yank_buffer and focused in blocks: asyncio.create_task(self.send_message({"type": "paste_block", "target_id": focused.block_id, "position": "before", "yank_data": self.yank_buffer}))
            elif event.key == "e" and isinstance(focused, BaseBlock): asyncio.create_task(focused.toggle_edit())
            elif event.key == "i" and isinstance(focused, CommandBlock): self.enter_control_mode(focused)
            elif event.key == "j" and isinstance(focused, CommandBlock): asyncio.create_task(self.send_message({"type": "run_block", "block_id": focused.block_id}))
            elif event.key == "ctrl+up": asyncio.create_task(self.action_move_up())
            elif event.key == "ctrl+down": asyncio.create_task(self.action_move_down())
        elif self.input_mode == "CONTROL":
            if event.key == "ctrl+escape":
                self.enter_normal_mode()
                return

            # Map common keys to ANSI sequences
            key_map = {
                "enter": "\r",
                "backspace": "\x7f",
                "tab": "\t",
                "up": "\x1b[A",
                "down": "\x1b[B",
                "right": "\x1b[C",
                "left": "\x1b[D",
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
                if len(char) == 1:
                    data = chr(ord(char.lower()) - ord('a') + 1)

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

    def on_unmount(self):
        if self.writer: self.writer.close()
        self.history.save()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemmi-Shell Client")
    parser.add_argument("-s", "--socket", default=DEFAULT_SOCKET_PATH, help="Path to the Unix Domain Socket")
    args = parser.parse_args()
    ClientApp(socket_path=args.socket).run()
