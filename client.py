import os
import json
import asyncio
import random
import re
import time
from typing import List, Dict

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, OptionList, Label, TextArea, Markdown, Button, Input
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.binding import Binding
from textual.screen import ModalScreen
from textual import work, on, events

SOCKET_PATH = "/tmp/gemmi_shell.sock"
THEME_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "theme.css")
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.txt")
WORKFLOW_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "termux_workflows.json")

# --- UTILS ---

def get_random_bright_color():
    colors = ["cyan", "magenta", "yellow", "green", "bright_blue", "bright_red", "orange1", "spring_green1"]
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
            self.styles.border_right = ("solid", user_color)
            if user_id != self.app_ref.user_id:
                self.query_one("#block_text_edit").disabled = True
            else:
                self.query_one("#block_text_edit").disabled = False
        else:
            self.styles.border_right = None
            self.query_one("#block_text_edit").disabled = False

class NoteBlock(BaseBlock):
    def compose(self) -> ComposeResult:
        yield Markdown(self.content, id="md_render", classes="markdown-content")
        yield TextArea(self.content, id="block_text_edit", classes="hidden", language="markdown")
        yield Label("[dim]Note (e: edit | ctrl+j: save)[/]", classes="block-info")

    def toggle_edit(self, remote=False):
        if not remote and self.locked_by and self.locked_by != self.app_ref.user_id:
            return # Block is locked by someone else

        self.is_editing = not self.is_editing
        render, edit = self.query_one("#md_render"), self.query_one("#block_text_edit")

        if self.is_editing:
            render.add_class("hidden")
            edit.remove_class("hidden")
            if not remote:
                edit.focus()
                self.app_ref.send_message({"type": "edit_start", "block_id": self.block_id})
        else:
            if not remote:
                self.content = edit.text
                self.app_ref.send_message({"type": "edit_save", "block_id": self.block_id, "content": self.content})

            render.update(self.content)
            render.remove_class("hidden")
            edit.add_class("hidden")

    def on_key(self, event: events.Key):
        if not self.is_editing and event.key == "e": self.toggle_edit()
        elif self.is_editing and event.key == "ctrl+j": self.toggle_edit()

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

    def toggle_edit(self, remote=False):
        if not remote and self.locked_by and self.locked_by != self.app_ref.user_id:
            return

        self.is_editing = not self.is_editing
        label, edit = self.query_one("#cmd_label"), self.query_one("#block_text_edit")

        if self.is_editing:
            label.add_class("hidden")
            edit.remove_class("hidden")
            if not remote:
                edit.focus()
                self.app_ref.send_message({"type": "edit_start", "block_id": self.block_id})
        else:
            if not remote:
                self.content = edit.text
                self.app_ref.send_message({"type": "edit_save", "block_id": self.block_id, "content": self.content})

            label.update(f"[bold blue]{self.cwd}[/]\n[white]{self.content}[/]")
            label.remove_class("hidden")
            edit.add_class("hidden")

    def on_key(self, event: events.Key):
        if not self.is_editing and event.key == "e": self.toggle_edit()
        elif self.is_editing and event.key == "ctrl+j": self.toggle_edit()

# --- APP ---

class ClientApp(App):
    CSS_PATH = THEME_FILE
    BINDINGS = [
        Binding("ctrl+q", "quit", "Exit"),
        Binding("ctrl+n", "toggle_mode", "CMD/NOTE"),
        Binding("ctrl+j", "submit", "Execute"),
        Binding("escape", "close_palette", "Close")
    ]

    def __init__(self):
        super().__init__()
        self.history = HistoryManager()
        self.input_mode = "CMD"
        self.user_color = get_random_bright_color()
        self.user_id = None
        self.blocks = {} # id: widget
        self.users = {} # id: color
        self.reader = None
        self.writer = None
        self._suppress_search = False
        self.workflows = load_workflows()

    def compose(self) -> ComposeResult:
        yield Header()
        with ScrollableContainer(id="command_history"):
            yield Static("[bold magenta]Gemmi-Shell Multi-User | Collaborative Notebook[/]")
        yield OptionList(id="palette")
        with Vertical(id="input_area"):
            with Horizontal():
                self.mode_label = Label(f"[bold cyan]MODE: COMMAND[/]", id="mode_indicator")
                yield self.mode_label
                self.user_label = Label(f"User: [bold {self.user_color}]Me[/]", id="user_indicator")
                yield self.user_label
            yield TextArea(language="bash", id="main_input")
        yield Footer()

    async def on_mount(self):
        self.query_one("#main_input").focus()
        await self.connect_to_server()

    async def connect_to_server(self):
        try:
            self.reader, self.writer = await asyncio.open_unix_connection(SOCKET_PATH)
            self.send_message({"type": "connect", "color": self.user_color})
            self.listen_to_server()
        except Exception as e:
            self.notify(f"Could not connect to server: {e}", variant="error")

    @work(exclusive=True)
    async def listen_to_server(self):
        while self.reader:
            try:
                line = await self.reader.readline()
                if not line: break
                msg = json.loads(line.decode())
                self.call_from_thread(self.handle_server_message, msg)
            except: break

    def send_message(self, msg):
        if self.writer:
            self.writer.write(json.dumps(msg).encode() + b"\n")
            asyncio.create_task(self.writer.drain())

    def handle_server_message(self, msg):
        msg_type = msg.get("type")

        if msg_type == "init":
            self.user_id = msg.get("your_id")
            self.users = msg.get("users", {})
            for block_data in msg.get("blocks", []):
                self.create_block(block_data)

        elif msg_type == "user_join":
            u_id, u_col = msg.get("user_id"), msg.get("color")
            self.users[u_id] = u_col
            self.notify(f"User {u_id[:4]} joined", variant="info")

        elif msg_type == "user_leave":
            u_id = msg.get("user_id")
            if u_id in self.users:
                del self.users[u_id]
                self.notify(f"User {u_id[:4]} left", variant="info")

        elif msg_type == "new_block":
            self.create_block(msg.get("block"))

        elif msg_type == "update_block":
            data = msg.get("block")
            b_id = data["id"]
            if b_id in self.blocks:
                block = self.blocks[b_id]
                block.content = data["content"]
                if isinstance(block, CommandBlock):
                    block.cwd = data["cwd"]
                    block.update_status(data["status"])
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

    def create_block(self, data):
        container = self.query_one("#command_history")
        b_id = data["id"]
        if b_id in self.blocks: return # Avoid duplicates

        if data["type"] == "NOTE":
            new_block = NoteBlock(b_id, data["content"], self)
        else:
            new_block = CommandBlock(b_id, data["content"], data["cwd"], self)
            new_block.full_output = data["output"]

        self.blocks[b_id] = new_block
        container.mount(new_block)

        if data["type"] == "CMD":
            new_block.update_status(data["status"])
            if data["output"]:
                new_block.query_one("#output").update(Text.from_ansi(data["output"]))

        if data["locked_by"]:
             new_block.update_lock(data["locked_by"], self.users.get(data["locked_by"], "white"))

        new_block.scroll_visible()

    def action_toggle_mode(self):
        self.input_mode = "NOTE" if self.input_mode == "CMD" else "CMD"
        c = "magenta" if self.input_mode == "NOTE" else "cyan"
        self.mode_label.update(f"[bold {c}]MODE: {self.input_mode}[/]")
        self.query_one("#main_input").language = "markdown" if self.input_mode == "NOTE" else "bash"

    def action_submit(self):
        ta = self.query_one("#main_input"); content = ta.text.strip()
        if not content: return
        ta.text = ""; self.query_one("#palette").remove_class("visible")
        self.history.add(content)
        self.send_message({
            "type": "submit",
            "mode": self.input_mode,
            "content": content,
            "cwd": os.getcwd()
        })

    # --- PALETTE LOGIC ---
    def update_palette(self, val: str):
        p = self.query_one("#palette"); p.clear_options()
        if not val.strip(): p.remove_class("visible"); return
        parts = val.split(); last = parts[-1] if parts else ""
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
        if "[green]Path:[/]" in label:
            path = label.split("] ")[1]; parts = inp.text.rsplit(None, 1)
            inp.text = (parts[0] + " " + path) if len(parts) > 1 else path
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
        p, inp = self.query_one("#palette"), self.query_one("#main_input")
        if event.key == "ctrl+p":
            event.prevent_default()
            if p.has_class("visible"): p.remove_class("visible")
            else: p.add_class("visible"); self.update_palette(inp.text)
            return
        vis = p.has_class("visible")
        if event.key in ("up", "down") and self.focused.id == "main_input" and vis:
            event.prevent_default()
            p.highlighted = max(0, min(p.option_count-1, (p.highlighted or 0) + (-1 if event.key == "up" else 1)))
            self.sync_input()
        elif event.key == "tab":
            event.prevent_default()
            if not vis: p.add_class("visible"); self.update_palette(inp.text)
            else: self.sync_input(); p.remove_class("visible")

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
                    else: node.focus()
                    node.last_click_time = now; return
                node = node.parent
        except: pass

    def on_unmount(self):
        if self.writer:
            self.writer.close()
        self.history.save()

if __name__ == "__main__":
    ClientApp().run()
