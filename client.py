import os
import json
import asyncio
import random
import re
import time
import argparse
import logging
from typing import List, Dict

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, OptionList, Label, TextArea, Markdown, Button, Input
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.binding import Binding
from textual.screen import ModalScreen
from textual import work, on, events, message

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
THEME_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "theme.css")
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.txt")
WORKFLOW_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "termux_workflows.json")

# --- UTILS ---

def get_random_bright_color():
    colors = ["cyan", "magenta", "yellow", "green", "blue", "red", "orange", "springgreen"]
    return random.choice(colors)

def fuzzy_match(query: str, target: str) -> bool:
    query, target = query.lower(), target.lower()
    it = iter(target)
    return all(c in it for c in query)

def load_workflows():
    if os.path.exists(WORKFLOW_FILE):
        try:
            with open(WORKFLOW_FILE, "r") as f: return json.load(f)
        except: pass
    return [{"name": "System Update", "cmd": "pkg update && pkg upgrade"}]

class HistoryManager:
    def __init__(self):
        self.cache = []
        self.load()
    def load(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    lines = [l.strip() for l in f if l.strip()]
                    self.cache = list(dict.fromkeys(lines[::-1]))[::-1]
            except: pass
    def add(self, cmd: str):
        if not cmd.strip(): return
        if cmd in self.cache: self.cache.remove(cmd)
        self.cache.append(cmd)
    def save(self):
        with open(HISTORY_FILE, "w") as f:
            for cmd in self.cache: f.write(f"{cmd}\n")
    def get_matches(self, query: str):
        q = query.lower()
        return [c for c in self.cache if q in c.lower()][-15:]

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
            wfs = load_workflows(); wfs.append({"name": n, "cmd": c})
            with open(WORKFLOW_FILE, "w") as f: json.dump(wfs, f, indent=4)
            self.dismiss(True)

# --- BLOCKS ---

class BaseBlock(Static):
    can_focus = True
    def __init__(self, block_id, content, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.block_id = block_id
        self.content = content
        self.app_ref = app_ref
        self.is_editing = False
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

class NoteBlock(BaseBlock):
    def compose(self) -> ComposeResult:
        yield Markdown(self.content, id="md_render", classes="markdown-content")
        yield TextArea(self.content, id="block_text_edit", classes="hidden", language="markdown")
        yield Label("[dim]Note (esc: leave edit | ctrl+j: save)[/]", classes="block-info")

    async def toggle_edit(self, remote=False, save=True):
        if not remote and self.locked_by and self.locked_by != self.app_ref.user_id:
            user_label = self.locked_by[:4] # Use short ID as fallback
            self.app_ref.notify(f"Block is locked by user {user_label}", severity="warning")
            return

        self.is_editing = not self.is_editing
        render, edit = self.query_one("#md_render"), self.query_one("#block_text_edit")

        if self.is_editing:
            render.add_class("hidden")
            edit.remove_class("hidden")
            if not remote:
                # Move cursor to end
                lines = edit.document.lines
                edit.cursor_location = (len(lines)-1, len(lines[-1]))
                edit.focus()
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
                self.app.enter_normal_mode()

    async def on_key(self, event: events.Key):
        if self.is_editing:
            if event.key == "escape":
                event.stop(); event.prevent_default(); await self.toggle_edit(save=False)
            elif event.key == "ctrl+j":
                event.stop(); event.prevent_default(); await self.toggle_edit(save=True)

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
    def __init__(self, block_id, command, cwd, app_ref, **kwargs):
        super().__init__(block_id, command, app_ref, **kwargs)
        self.cwd = cwd
        self.full_output = ""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="block-header"):
            yield Label("➜", classes="prompt-symbol")
            yield Label(f"[bold blue]{self.cwd}[/]\n[white]{self.content}[/]", id="cmd_label")
            yield TextArea(self.content, id="block_text_edit", classes="hidden", language="bash")
        yield Static("", id="output", classes="block-output", markup=False)
        yield Label("[grey44]Ready[/]", id="info", classes="block-info")

    def append_output(self, text: str):
        self.full_output += text
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

    async def toggle_edit(self, remote=False, save=True):
        if not remote and self.locked_by and self.locked_by != self.app_ref.user_id:
            user_label = self.locked_by[:4]
            self.app_ref.notify(f"Block is locked by user {user_label}", severity="warning")
            return

        self.is_editing = not self.is_editing
        label, edit = self.query_one("#cmd_label"), self.query_one("#block_text_edit")

        if self.is_editing:
            label.add_class("hidden")
            edit.remove_class("hidden")
            if not remote:
                lines = edit.document.lines
                edit.cursor_location = (len(lines)-1, len(lines[-1]))
                edit.focus()
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
                self.app.enter_normal_mode()

    async def on_key(self, event: events.Key):
        if self.is_editing:
            if event.key == "escape":
                event.stop(); event.prevent_default(); await self.toggle_edit(save=False)
            elif event.key == "ctrl+j":
                event.stop(); event.prevent_default(); await self.toggle_edit(save=True)
        elif event.key == "ctrl+c":
            await self.app_ref.send_message({"type": "stop_process", "block_id": self.block_id})

# --- APP ---

class ClientApp(App):
    CSS_PATH = THEME_FILE

    def _on_mouse_event(self, event: events.MouseEvent) -> None:
        # Disable mouse as requested in vimify
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
        self.input_mode = "NORMAL" # NORMAL, INPUT, SELECTION
        self.user_color = get_random_bright_color()
        self.user_id = None
        self.blocks = {} # id: widget
        self.users = {} # id: color
        self.reader = None
        self.writer = None
        self._suppress_search = False
        self.workflows = load_workflows()
        self.yank_buffer = None
        self.count_str = ""
        self.available_commands = ["export", "import", "exit", "save_wf", "help", "clear"]

    def compose(self) -> ComposeResult:
        with Horizontal(id="filter_bar", classes="hidden"):
            yield Label(" 🔍 Filter: ", id="filter_label")
            yield Input(placeholder="Search blocks...", id="filter_input")
        with ScrollableContainer(id="command_history"):
            yield Static("[bold magenta]Gemmi-Shell Multi-User | Collaborative Notebook[/]")
        with Vertical(id="bottom_dock"):
            yield OptionList(id="palette")
            with Horizontal(id="input_header"):
                self.mode_label = Label(f"[bold cyan]MODE: NORMAL[/]", id="mode_indicator")
                yield self.mode_label
                self.user_label = Label(f"User: [bold {self.user_color}]Me[/]", id="user_indicator")
                yield self.user_label
            yield NotebookInput(language="bash", id="main_input")

    def on_mount(self):
        self.run_worker(self.connect_to_server())
        self.enter_normal_mode()
        self.set_interval(0.5, self.update_running_statuses)

    def update_running_statuses(self):
        # Local visual update for running processes if needed,
        # but server should be pushing updates.
        # This can be used for local timers if we add them to blocks.
        pass

    def on_ready(self):
        self.query_one("#main_input").focus()

    async def connect_to_server(self):
        try:
            self.reader, self.writer = await asyncio.open_unix_connection(
                self.socket_path, limit=10 * 1024 * 1024
            )
            await self.send_message({"type": "connect", "color": self.user_color})
            await self.listen_to_server()
        except Exception as e:
            self.notify(f"Could not connect to server: {e}", severity="error")

    async def listen_to_server(self):
        logging.info("Starting listener loop")
        while self.reader and not self.reader.at_eof():
            try:
                line = await self.reader.readline()
                if not line:
                    logging.info("Server closed connection")
                    break

                try:
                    data = line.decode().strip()
                    if not data: continue
                    msg = json.loads(data)
                    logging.debug(f"Received msg: {msg.get('type')}")
                    self.post_message(ServerMessage(msg))
                except Exception as e:
                    logging.error(f"Error handling message: {e}")
                    continue

            except asyncio.LimitOverrunError as e:
                logging.error(f"Buffer limit exceeded: {e}")
                await self.reader.read(e.consumed)
            except Exception as e:
                logging.error(f"Listener loop error: {e}")
                break
        logging.info("Listener loop stopped")

    async def send_message(self, msg):
        if self.writer:
            try:
                self.writer.write(json.dumps(msg).encode() + b"\n")
                await self.writer.drain()
            except Exception as e:
                logging.error(f"Send error: {e}")

    async def on_server_message(self, event: ServerMessage):
        msg = event.data
        msg_type = msg.get("type")
        logging.info(f"Processing server message: {msg_type}")

        if msg_type == "init":
            focused_id = None
            if self.focused and isinstance(self.focused, BaseBlock):
                focused_id = self.focused.block_id

            new_id = msg.get("your_id")
            if new_id and new_id != "all":
                self.user_id = new_id
            self.users = msg.get("users", {})
            # Clear UI and local blocks to avoid duplicates
            container = self.query_one("#command_history")
            for b_id in list(self.blocks.keys()):
                try: self.blocks[b_id].remove()
                except: pass
            self.blocks = {}
            for block_data in msg.get("blocks", []):
                await self.create_block(block_data)

            if focused_id and focused_id in self.blocks:
                self.call_after_refresh(self.blocks[focused_id].focus)

        elif msg_type == "user_join":
            u_id, u_col = msg.get("user_id"), msg.get("color")
            self.users[u_id] = u_col
            self.notify(f"User {u_id[:4]} joined", severity="information")

        elif msg_type == "user_leave":
            u_id = msg.get("user_id")
            if u_id in self.users:
                del self.users[u_id]
                self.notify(f"User {u_id[:4]} left", severity="information")

        elif msg_type == "new_block":
            logging.info(f"Adding new block from server: {msg.get('block', {}).get('id')}")
            await self.create_block(msg.get("block"))
            self.refresh()

        elif msg_type == "reorder":
            focused_id = None
            if self.focused and isinstance(self.focused, BaseBlock):
                focused_id = self.focused.block_id

            # Clear all blocks and recreate in new order
            container = self.query_one("#command_history")
            for b_id in list(self.blocks.keys()):
                try: self.blocks[b_id].remove()
                except: pass
            self.blocks = {}
            for block_data in msg.get("blocks", []):
                await self.create_block(block_data)

            if focused_id and focused_id in self.blocks:
                # Use call_after_refresh to ensure focus is applied to the newly mounted widget
                self.call_after_refresh(self.blocks[focused_id].focus)

        elif msg_type == "update_block":
            data = msg.get("block")
            b_id = data["id"]
            if b_id in self.blocks:
                block = self.blocks[b_id]
                block.content = data["content"]
                if isinstance(block, CommandBlock):
                    block.cwd = data["cwd"]
                    block.update_status(data["status"])
                    # Sync output to handle reruns properly
                    block.full_output = data.get("output", "")
                    block.query_one("#output").update(Text.from_ansi(block.full_output))
                # Refresh UI
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
                self.blocks[b_id].update_lock(msg.get("user_id"), msg.get("user_color"))

        elif msg_type == "unlock":
            b_id = msg.get("block_id")
            if b_id in self.blocks:
                self.blocks[b_id].update_lock(None, None)

        elif msg_type == "remove_block":
            b_id = msg.get("block_id")
            if b_id in self.blocks:
                self.blocks[b_id].remove()
                del self.blocks[b_id]

    async def create_block(self, data):
        b_id = data["id"]
        if b_id in self.blocks:
            logging.debug(f"Block {b_id} already exists, skipping create")
            return # Avoid duplicates

        logging.info(f"Creating block: {b_id} ({data['type']})")
        if data["type"] == "NOTE":
            new_block = NoteBlock(b_id, data["content"], self)
        else:
            new_block = CommandBlock(b_id, data["content"], data["cwd"], self)
            new_block.full_output = data["output"]

        self.blocks[b_id] = new_block

        container = self.query_one("#command_history")
        await container.mount(new_block)
        logging.info(f"Block {b_id} mounted to container")

        if data["type"] == "CMD":
            new_block.update_status(data["status"])
            if data["output"]:
                new_block.query_one("#output").update(Text.from_ansi(data["output"]))

        if data["locked_by"]:
                new_block.update_lock(data["locked_by"], self.users.get(data["locked_by"], "white"))

        self.call_after_refresh(new_block.scroll_visible)

    def action_esc_pressed(self):
        bar = self.query_one("#filter_bar")
        if not bar.has_class("hidden"):
            self.action_toggle_filter()
        self.enter_normal_mode()

    def enter_normal_mode(self):
        self.input_mode = "NORMAL"
        self.count_str = ""
        self.update_mode_label()
        self.query_one("#palette").remove_class("visible")
        self.query_one("#main_input").text = ""
        self.screen.focus()

    def enter_selection_mode(self):
        self.input_mode = "SELECTION"
        self.update_mode_label()
        container = self.query_one("#command_history")
        blocks = [c for c in container.children if isinstance(c, BaseBlock)]
        if blocks:
            blocks[-1].focus()
            blocks[-1].scroll_visible()

    def enter_input_mode(self, prefix=""):
        self.input_mode = "INPUT"
        self.update_mode_label()
        inp = self.query_one("#main_input")
        if prefix:
            inp.text = prefix
            inp.cursor_location = (0, len(prefix))
        inp.focus()

    def update_mode_label(self):
        if not hasattr(self, "mode_label"): return
        colors = {"NORMAL": "#757575", "INPUT": "#7c4dff", "SELECTION": "#00e676"}
        c = colors.get(self.input_mode, "#7c4dff")
        self.mode_label.update(f"[bold {c}]MODE: {self.input_mode}[/]")

    async def action_submit(self):
        ta = self.query_one("#main_input"); full_text = ta.text
        if not full_text.strip() and not any(full_text.startswith(p) for p in ("!", ":", ";")):
            ta.text = ""; return
        ta.text = ""; self.query_one("#palette").remove_class("visible")

        if full_text.startswith(":"):
            await self.handle_internal_command(full_text[1:])
            self.enter_normal_mode()
            return

        if full_text.startswith("!"):
            content = full_text[1:].strip()
            self.history.add(content)
            # Handle local directory changes for CD commands
            if content.startswith("cd "):
                try:
                    target = content[3:].strip()
                    if not target: target = "~"
                    os.chdir(os.path.expanduser(target))
                    container = self.query_one("#command_history")
                    await container.mount(Label(f"[dim]➜ {os.getcwd()}[/]"))
                    self.enter_normal_mode()
                    return
                except Exception as e:
                    self.notify(f"CD Error: {e}", severity="error")
                    return

            await self.send_message({
                "type": "submit",
                "mode": "CMD",
                "content": content,
                "cwd": os.getcwd()
            })
        elif full_text.startswith(";"):
            content = full_text[1:].strip()
            await self.send_message({
                "type": "submit",
                "mode": "NOTE",
                "content": content,
                "cwd": os.getcwd()
            })
        else:
            self.notify("Use ! for bash, ; for note, : for commands", severity="warning")
            ta.text = full_text
            return

        self.enter_normal_mode()

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
            for block in self.blocks.values():
                block.remove_class("filtered-out")
            self.enter_normal_mode()

    @on(Input.Changed, "#filter_input")
    def filter_blocks(self, event: Input.Changed):
        query = event.value.lower()
        for block in self.blocks.values():
            search_text = ""
            if isinstance(block, CommandBlock):
                search_text = (block.content + block.full_output).lower()
            else:
                search_text = block.content.lower()

            if not query or query in search_text:
                block.remove_class("filtered-out")
            else:
                block.add_class("filtered-out")

    async def handle_internal_command(self, cmd_line):
        parts = cmd_line.split(" ", 1)
        cmd = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "export": self.export_notebook(args or f"session_{int(time.time())}.md")
        elif cmd == "import": await self.import_notebook(args)
        elif cmd == "exit": self.exit()
        elif cmd == "save_wf": self.action_save_wf_dialog()
        elif cmd == "clear":
             await self.send_message({"type": "clear_session"})
        elif cmd == "help":
            self.notify("Commands: export [file], import [file], exit, save_wf, clear, help")
        else:
            self.notify(f"Unknown command: {cmd}", severity="error")

    # --- EXPORT / IMPORT LOGIC ---
    def action_save_notebook_dialog(self):
        self.push_screen(SaveNotebookModal(), self.export_notebook)

    def action_import_notebook_dialog(self):
        self.push_screen(ImportNotebookModal(), lambda f: asyncio.create_task(self.import_notebook(f)))

    def export_notebook(self, filename: str):
        if not filename: return
        md_output = [f"# Shell Notebook Export - {time.strftime('%Y-%m-%d %H:%M:%S')}\n"]
        for block_id, widget in self.blocks.items():
            if isinstance(widget, NoteBlock):
                md_output.append(f"{widget.content}\n")
            elif isinstance(widget, CommandBlock):
                md_output.append(f"```bash\n{widget.content}\n```\n")
                if widget.full_output.strip():
                    clean = re.sub(r'\x1B[@-_][0-?]*[ -/]*[@-~]', '', widget.full_output)
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
            last_pos = 0
            new_blocks = []
            matches = list(pattern.finditer(content))
            for match in matches:
                before = content[last_pos:match.start()].strip()
                if before:
                    lines = [l for l in before.splitlines() if not l.strip().startswith("# Shell Notebook Export")]
                    clean_before = "\n".join(lines).strip()
                    if clean_before: new_blocks.append({"type": "NOTE", "content": clean_before})
                lang, code = match.groups()
                if lang == "bash":
                    new_blocks.append({"type": "CMD", "content": code, "cwd": os.getcwd()})
                elif lang == "text" and new_blocks and new_blocks[-1]["type"] == "CMD":
                    new_blocks[-1]["output"] = code
                last_pos = match.end()
            after = content[last_pos:].strip()
            if after:
                lines = [l for l in after.splitlines() if not l.strip().startswith("# Shell Notebook Export")]
                clean_after = "\n".join(lines).strip()
                if clean_after: new_blocks.append({"type": "NOTE", "content": clean_after})

            await self.send_message({"type": "import_blocks", "blocks": new_blocks})
            self.notify(f"Notebook Imported: {filename}", severity="information")
        except Exception as e:
            self.notify(f"Import Error: {e}", severity="error")

    async def action_move_up(self):
        focused = self.focused
        if focused and isinstance(focused, BaseBlock):
            await self.send_message({"type": "move_block", "block_id": focused.block_id, "direction": "up"})

    async def action_move_down(self):
        focused = self.focused
        if focused and isinstance(focused, BaseBlock):
            await self.send_message({"type": "move_block", "block_id": focused.block_id, "direction": "down"})

    async def action_delete_block(self):
        focused = self.focused
        if focused and isinstance(focused, BaseBlock):
            if focused.locked_by and focused.locked_by != self.user_id:
                user_label = focused.locked_by[:4]
                self.notify(f"Block is locked by user {user_label}", severity="warning")
                return
            await self.send_message({"type": "delete_block", "block_id": focused.block_id})

    def action_save_wf_dialog(self):
        self.push_screen(SaveWorkflowModal(self.query_one("#main_input").text), lambda s: s and setattr(self, 'workflows', load_workflows()))

    # --- PALETTE LOGIC ---
    def _get_current_token(self, text: str) -> str:
        if not text or text.endswith(" "): return ""
        parts = re.findall(r'(?:[^\s"\']|"(?:\\.|[^"])*"|\'(?:\\.|[^\'])*\')+', text)
        return parts[-1] if parts else ""

    def update_palette(self, val: str):
        p = self.query_one("#palette"); p.clear_options()
        if not val.strip() and not val.endswith(" "): p.remove_class("visible"); return

        if val.startswith(":"):
            cmd_part = val[1:].split(" ")[0]
            for c in self.available_commands:
                if fuzzy_match(cmd_part, c):
                    p.add_option(f"[bold cyan]CMD:[/] {c}")

        token = self._get_current_token(val)
        last = token.strip("\"'")
        d_p = os.path.dirname(last) if last else ""; f_q = os.path.basename(last) if last else ""
        ex_d = os.path.expanduser(d_p) if d_p else "."
        try:
            if os.path.isdir(ex_d):
                for f in os.listdir(ex_d):
                    if fuzzy_match(f_q, f):
                        full = os.path.join(d_p, f) if d_p else f
                        if os.path.isdir(os.path.join(ex_d, f)): full += "/"
                        p.add_option(f"[green]Path:[/] {full}")
        except: pass
        for h in self.history.get_matches(val): p.add_option(f"[yellow]Hist:[/] {h}")
        for wf in self.workflows:
            if fuzzy_match(val, wf['name']) or fuzzy_match(val, wf['cmd']):
                p.add_option(f"[cyan]WF:[/] {wf['name']} ([dim]{wf['cmd'][:20]}...[/])")
        if p.option_count > 0: p.add_class("visible")
        else: p.remove_class("visible")

    def sync_input(self):
        p = self.query_one("#palette")
        if p.highlighted is None: return
        option = p.get_option_at_index(p.highlighted)
        label = str(option.prompt)
        inp = self.query_one("#main_input"); self._suppress_search = True
        if "[bold cyan]CMD:[/] " in label:
            cmd = label.split("] ")[1]
            inp.text = ":" + cmd
        elif "[green]Path:[/]" in label:
            path = label.split("] ")[1]
            if " " in path: path = f'"{path}"'
            token = self._get_current_token(inp.text)
            if token:
                inp.text = inp.text[:inp.text.rfind(token)] + path
            else:
                inp.text += path
        else:
            cmd = label.split("] ", 1)[1]
            if "[cyan]WF:[/]" in label:
                name = label.split("] ")[1].split(" (")[0]
                cmd = next((wf['cmd'] for wf in self.workflows if wf['name'] == name), cmd)
            inp.text = cmd
        lines = inp.document.lines
        inp.cursor_location = (len(lines)-1, len(lines[-1]))

    @on(OptionList.OptionSelected, "#palette")
    def opt_sel(self, event):
        self.sync_input(); self.query_one("#palette").remove_class("visible"); self.query_one("#main_input").focus()

    def on_key(self, event: events.Key):
        # Global escape to normal mode
        if event.key == "escape":
            self.enter_normal_mode()
            return

        p, inp = self.query_one("#palette"), self.query_one("#main_input")

        if self.input_mode == "NORMAL":
            if event.character == "!":
                self.enter_input_mode(prefix="!")
            elif event.character == ":":
                self.enter_input_mode(prefix=":")
            elif event.character == ";":
                self.enter_input_mode(prefix=";")
            elif event.character == "s":
                self.enter_selection_mode()
            return

        if self.input_mode == "INPUT":
            # Palette logic
            vis = p.has_class("visible")
            if event.key == "ctrl+p":
                event.prevent_default()
                if vis: p.remove_class("visible")
                else: p.add_class("visible"); self.update_palette(inp.text)
            elif event.key in ("up", "down") and vis:
                event.prevent_default()
                p.highlighted = max(0, min(p.option_count-1, (p.highlighted or 0) + (-1 if event.key == "up" else 1)))
                self.sync_input()
            elif event.key == "tab":
                event.prevent_default()
                if not vis: p.add_class("visible"); self.update_palette(inp.text)
                else: self.sync_input(); p.remove_class("visible")

        elif self.input_mode == "SELECTION":
            container = self.query_one("#command_history")
            focused = self.focused
            blocks = [c for c in container.children if isinstance(c, BaseBlock)]

            if event.character and event.character.isdigit() and event.character != "0":
                self.count_str += event.character; return
            elif event.character == "0" and self.count_str:
                self.count_str += event.character; return

            count = int(self.count_str) if self.count_str else 1
            self.count_str = ""

            if event.character in (":", "!", ";"):
                self.enter_input_mode(prefix=event.character)
                return

            if event.key in ("up", "down", "k", "j") and not (event.key == "j" and isinstance(focused, CommandBlock) and not focused.is_editing):
                 if not blocks: return
                 idx = blocks.index(focused) if focused in blocks else 0
                 step = count if event.key in ("down", "j") else -count
                 new_idx = max(0, min(len(blocks)-1, idx + step))
                 blocks[new_idx].focus(); blocks[new_idx].scroll_visible()
            elif event.key == "x":
                 asyncio.create_task(self.action_delete_block())
            elif event.key == "y":
                 if isinstance(focused, NoteBlock):
                     self.yank_buffer = ("NOTE", focused.content)
                     self.notify("Note yanked")
                 elif isinstance(focused, CommandBlock):
                     self.yank_buffer = ("CMD", focused.content, focused.cwd)
                     self.notify("Command yanked")
            elif event.key == "p": # Paste below
                 if self.yank_buffer and focused in blocks:
                     asyncio.create_task(self.send_message({
                         "type": "paste_block",
                         "target_id": focused.block_id,
                         "position": "after",
                         "yank_data": self.yank_buffer
                     }))
            elif event.key == "P": # Paste above
                 if self.yank_buffer and focused in blocks:
                     asyncio.create_task(self.send_message({
                         "type": "paste_block",
                         "target_id": focused.block_id,
                         "position": "before",
                         "yank_data": self.yank_buffer
                     }))
            elif event.key == "e":
                 if isinstance(focused, BaseBlock): asyncio.create_task(focused.toggle_edit())
            elif event.key == "j":
                 if isinstance(focused, CommandBlock):
                     asyncio.create_task(self.send_message({"type": "run_block", "block_id": focused.block_id}))
            elif event.key == "ctrl+up": asyncio.create_task(self.action_move_up())
            elif event.key == "ctrl+down": asyncio.create_task(self.action_move_down())

    @on(TextArea.Changed, "#main_input")
    def in_ch(self, event):
        if not self._suppress_search and self.query_one("#palette").has_class("visible"):
            self.update_palette(event.text_area.text)
        self._suppress_search = False

    def on_click(self, event: events.Click):
        try:
            widget, _ = self.screen.get_widget_at(event.screen_x, event.screen_y)
            node = widget
            while node:
                if isinstance(node, BaseBlock):
                    now = time.time()
                    if now - node.last_click_time < 0.4:
                        self.query_one("#main_input").text = node.content
                        self.query_one("#main_input").focus()
                    else:
                        node.focus()
                        # If already editing, focus the text area
                        if node.is_editing:
                            node.query_one("#block_text_edit").focus()
                    node.last_click_time = now; return
                node = node.parent
        except: pass

    def on_unmount(self):
        if self.writer:
            self.writer.close()
        self.history.save()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemmi-Shell Client")
    parser.add_argument("-s", "--socket", default=DEFAULT_SOCKET_PATH, help="Path to the Unix Domain Socket")
    args = parser.parse_args()
    ClientApp(socket_path=args.socket).run()
