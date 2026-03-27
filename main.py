import os
import pty
import subprocess
import json
import signal
import time
import re
from typing import List

from rich.text import Text
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, OptionList, Label, TextArea, Markdown, Button, Input
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.binding import Binding
from textual.screen import ModalScreen
from textual import work, on, events

# --- KONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_FILE = os.path.join(BASE_DIR, "termux_workflows.json")
HISTORY_FILE = os.path.join(BASE_DIR, "history.txt")
THEME_FILE = os.path.join(BASE_DIR, "theme.css")
BASH_EXE = "/data/data/com.termux/files/usr/bin/bash" if os.path.exists("/data/data/com.termux/files/usr/bin/bash") else "/bin/bash"

def load_workflows():
    if os.path.exists(WORKFLOW_FILE):
        try:
            with open(WORKFLOW_FILE, "r") as f: return json.load(f)
        except: pass
    return [{"name": "System Update", "cmd": "pkg update && pkg upgrade"}]

def fuzzy_match(query: str, target: str) -> bool:
    if not query: return True
    query, target = query.lower(), target.lower()
    it = iter(target)
    return all(c in it for c in query)

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
        if not query: return self.cache[-15:]
        return [c for c in self.cache if fuzzy_match(query, c)][-15:]

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
            yield Label("[bold cyan]Notebook importieren (.md)[/]")
            yield Input(placeholder="dateiname.md", id="file_name")
            with Horizontal(id="modal_buttons"):
                yield Button("Abbrechen", variant="error", id="cancel")
                yield Button("Importieren", variant="success", id="import")
    @on(Button.Pressed, "#cancel")
    def cancel(self): self.dismiss(None)
    @on(Button.Pressed, "#import")
    def import_nb(self):
        name = self.query_one("#file_name").value
        if not name.endswith(".md"): name += ".md"
        self.dismiss(name)

class SaveWorkflowModal(ModalScreen):
    def __init__(self, text: str):
        super().__init__()
        self.text = text
    def compose(self) -> ComposeResult:
        with Vertical(id="modal_dialog"):
            yield Label("[bold magenta]Als Workflow speichern[/]")
            yield Input(placeholder="Name...", id="wf_name")
            yield TextArea(self.text, id="wf_cmd", language="bash")
            with Horizontal(id="modal_buttons"):
                yield Button("Abbrechen", variant="error", id="cancel")
                yield Button("Speichern", variant="success", id="save")
    @on(Button.Pressed, "#cancel")
    def cancel(self): self.dismiss(None)
    @on(Button.Pressed, "#save")
    def save(self):
        n, c = self.query_one("#wf_name").value, self.query_one("#wf_cmd").text
        if n and c:
            wfs = load_workflows(); wfs.append({"name": n, "cmd": c})
            with open(WORKFLOW_FILE, "w") as f: json.dump(wfs, f, indent=4)
            self.dismiss(True)

# --- BLÖCKE ---

class NoteBlock(Static):
    can_focus = True
    def __init__(self, content: str, **kwargs):
        super().__init__(**kwargs)
        self.content, self.is_editing, self.last_click_time = content, False, 0
    def compose(self) -> ComposeResult:
        yield Markdown(self.content, id="md_render", classes="markdown-content")
        yield TextArea(self.content, id="block_text_edit", classes="hidden", language="markdown")
        yield Label("[dim]Note (esc: leave edit | ctrl+j: save)[/]", classes="block-info")
    def toggle_edit(self, save=True):
        self.is_editing = not self.is_editing
        render, edit = self.query_one("#md_render"), self.query_one("#block_text_edit")
        if self.is_editing:
            render.add_class("hidden"); edit.remove_class("hidden"); edit.focus()
        else:
            if save: self.content = edit.text
            else: edit.text = self.content
            render.update(self.content); render.remove_class("hidden"); edit.add_class("hidden")
            self.app.enter_normal_mode()
    def on_key(self, event: events.Key):
        if self.is_editing:
            if event.key == "escape":
                event.stop(); event.prevent_default(); self.toggle_edit(save=False)
            elif event.key == "ctrl+j":
                event.stop(); event.prevent_default(); self.toggle_edit(save=True)

class NotebookInput(TextArea):
    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.app.action_submit()
        elif event.key in ("ctrl+enter", "ctrl+j", "ctrl+m"):
            event.stop()
            event.prevent_default()
            self.insert("\n")
        elif event.key == "escape":
            event.stop()
            event.prevent_default()
            self.app.enter_normal_mode()

class CommandBlock(Static):
    can_focus = True
    def __init__(self, command: str, cwd: str, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.command, self.cwd, self.app_ref = command, cwd, app_ref
        self.full_output, self.proc_active, self.process, self.is_editing, self.last_click_time = "", False, None, False, 0
        self.start_time = 0
    def compose(self) -> ComposeResult:
        with Horizontal(classes="block-header"):
            yield Label("➜", classes="prompt-symbol")
            with Vertical(classes="command-container"):
                yield Label(f"[bold blue]{self.cwd}[/]", id="cwd_label")
                with Static(id="cmd_wrapper"):
                    yield Static(Syntax(self.command, "bash", theme="monokai"), id="cmd_syntax")
                    yield TextArea(self.command, id="block_text_edit", classes="hidden", language="bash")
        yield Static("", id="output", classes="block-output", markup=False)
        yield Label("[grey44]Ready[/]", id="info", classes="block-info")

    def update_status(self):
        if self.proc_active:
            elapsed = time.time() - self.start_time
            self.query_one("#info").update(f"[yellow]⏳ {elapsed:.1f}s[/]")
    def append_output(self, text: str):
        # Basic terminal emulation for interactive commands like 'watch'
        if "\x1b[H" in text or "\x1b[2J" in text:
            idx = max(text.rfind("\x1b[H"), text.rfind("\x1b[2J"))
            self.full_output = text[idx:]
        else:
            text = re.sub(r'\x1b\][0-9]*;.*?\x07', '', text)
            text = re.sub(r'\x1b\][0-9]*;.*?\x1b\\', '', text)
            self.full_output += text

        if len(self.full_output) > 30000:
            self.full_output = "...(truncated)...\n" + self.full_output[-30000:]

        try:
            self.query_one("#output").update(Text.from_ansi(self.full_output))
        except: pass
    def finish(self, code: int):
        self.proc_active = False
        elapsed = time.time() - self.start_time
        status = "[green]✅ OK[/]" if code == 0 else f"[red]❌ ERR({code})[/]"
        self.query_one("#info").update(f"{status} [dim]({elapsed:.1f}s)[/]")
        self.remove_class("running")
    def toggle_edit(self, save=True, run=True):
        self.is_editing = not self.is_editing
        syntax, edit = self.query_one("#cmd_syntax"), self.query_one("#block_text_edit")
        if self.is_editing:
            syntax.add_class("hidden"); edit.remove_class("hidden"); edit.focus()
        else:
            if save: self.command = edit.text
            else: edit.text = self.command
            syntax.update(Syntax(self.command, "bash", theme="monokai"))
            syntax.remove_class("hidden"); edit.add_class("hidden")
            if save and run: self.run_process()
            self.app.enter_normal_mode()

    def run_process(self):
        self.full_output = ""; self.query_one("#output").update(""); self.add_class("running")
        self.start_time = time.time()
        self.app_ref.start_process(self.command, self)
    def on_key(self, event: events.Key):
        if self.is_editing:
            if event.key == "escape":
                event.stop(); event.prevent_default(); self.toggle_edit(save=False)
            elif event.key == "ctrl+j":
                event.stop(); event.prevent_default(); self.toggle_edit(save=True)
        elif event.key == "ctrl+c" and self.process:
            try: os.killpg(os.getpgid(self.process.pid), signal.SIGINT)
            except: pass

# --- APP ---

class ShellApp(App):
    CSS_PATH = THEME_FILE

    def _on_mouse_event(self, event: events.MouseEvent) -> None:
        # Disable mouse as requested
        event.stop()
        event.prevent_default()

    BINDINGS = [
        Binding("ctrl+q", "quit", "Exit"),
        Binding("escape", "esc_pressed", "Back/Clear")
    ]

    def __init__(self):
        super().__init__()
        self.history = HistoryManager()
        self.input_mode = "NORMAL" # NORMAL, INPUT, SELECTION
        self.active_processes, self._suppress_search = [], False
        self.yank_buffer = None
        self.count_str = ""
        self.current_prefix = ""
        self.available_commands = ["export", "import", "exit", "save_wf", "help", "clear"]

    def compose(self) -> ComposeResult:
        yield Header()
        with ScrollableContainer(id="command_history"):
            yield Static("[bold #7c4dff]G E M M I - S H E L L[/] [bold #e1e1e6]v12.0[/] | [italic #88888e]Notebook Chronicler[/]")
        with Vertical(id="bottom_dock"):
            yield OptionList(id="palette")
            self.mode_label = Label("[bold #757575]MODE: NORMAL[/]", id="mode_indicator")
            yield self.mode_label
            with Horizontal(id="input_container"):
                yield Label("", id="mode_prefix")
                yield NotebookInput(language="bash", id="main_input")

    def on_mount(self):
        self.workflows = load_workflows()
        self.query_one("#main_input").language = "bash"
        self.enter_normal_mode()
        self.set_interval(0.5, self.update_running_statuses)

    def focus_input(self):
        self.query_one("#main_input").focus()

    def update_running_statuses(self):
        for widget in self.query_one("#command_history").children:
            if isinstance(widget, CommandBlock) and widget.proc_active:
                widget.update_status()

    def action_esc_pressed(self):
        self.enter_normal_mode()

    def enter_normal_mode(self):
        self.input_mode = "NORMAL"
        self.count_str = ""
        self.current_prefix = ""
        self.update_mode_label()
        self.query_one("#mode_prefix").update("")
        self.query_one("#palette").remove_class("visible")

        inp = self.query_one("#main_input")
        inp.text = ""
        inp.disabled = True

        # Ensure nothing focusable in blocks or input is focused
        self.screen.focus()

    def enter_selection_mode(self):
        self.input_mode = "SELECTION"
        self.update_mode_label()
        self.query_one("#main_input").disabled = True
        container = self.query_one("#command_history")
        blocks = [c for c in container.children if isinstance(c, (CommandBlock, NoteBlock))]
        if blocks:
            # Focus the last block by default as it is usually the most relevant
            blocks[-1].focus()
            blocks[-1].scroll_visible()

    def enter_input_mode(self, prefix=""):
        mode_map = {"!": "BASH", ":": "CMD", ";": "NOTE"}
        self.input_mode = mode_map.get(prefix, "INPUT")
        self.current_prefix = prefix
        self.update_mode_label()

        pref_label = self.query_one("#mode_prefix")
        pref_label.update(prefix)

        colors = {"BASH": "#00e676", "CMD": "#7c4dff", "NOTE": "#ff5252"}
        c = colors.get(self.input_mode, "#7c4dff")
        pref_label.styles.color = c

        inp = self.query_one("#main_input")
        inp.disabled = False
        if prefix == ":": inp.language = "bash"
        elif prefix == "!": inp.language = "bash"
        elif prefix == ";": inp.language = "markdown"

        self.focus_input()

    def update_mode_label(self):
        if not hasattr(self, "mode_label"): return
        colors = {"NORMAL": "#757575", "BASH": "#00e676", "CMD": "#7c4dff", "NOTE": "#ff5252", "SELECTION": "#00b0ff"}
        c = colors.get(self.input_mode, "#7c4dff")
        self.mode_label.update(f"[bold {c}]MODE: {self.input_mode}[/]")

    # --- PALETTE LOGIC ---
    def _get_current_token(self, text: str) -> str:
        if not text or text.endswith(" "): return ""
        parts = re.findall(r'(?:[^\s"\']|"(?:\\.|[^"])*"|\'(?:\\.|[^\'])*\')+', text)
        return parts[-1] if parts else ""

    def update_palette(self, val: str):
        p = self.query_one("#palette"); p.clear_options()
        if not val.strip() and not val.endswith(" "): p.remove_class("visible"); return

        if self.input_mode == "CMD":
            for c in self.available_commands:
                if fuzzy_match(val, c):
                    p.add_option(f"[bold cyan]CMD:[/] {c}")
        elif self.input_mode == "BASH":
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
            inp.text = cmd
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
                event.stop(); event.prevent_default()
            elif event.character == ":":
                self.enter_input_mode(prefix=":")
                event.stop(); event.prevent_default()
            elif event.character == ";":
                self.enter_input_mode(prefix=";")
                event.stop(); event.prevent_default()
            elif event.character == "s":
                self.enter_selection_mode()
                event.stop(); event.prevent_default()
            return

        if self.input_mode in ("BASH", "CMD", "NOTE", "INPUT"):
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
            blocks = [c for c in container.children if isinstance(c, (CommandBlock, NoteBlock))]

            if event.character and event.character.isdigit() and event.character != "0":
                # Start or continue count. '0' is usually a command in vim (start of line)
                # but let's keep it simple. If count_str is empty, '0' might be a command.
                self.count_str += event.character; return
            elif event.character == "0" and self.count_str:
                self.count_str += event.character; return

            count = int(self.count_str) if self.count_str else 1
            self.count_str = ""

            if event.character in (":", "!", ";"):
                self.enter_input_mode(prefix=event.character)
                return

            if event.key in ("up", "down", "k", "j") and not (event.key == "j" and isinstance(focused, CommandBlock)):
                if not blocks: return
                idx = blocks.index(focused) if focused in blocks else 0
                step = count if event.key in ("down", "j") else -count
                new_idx = max(0, min(len(blocks)-1, idx + step))
                blocks[new_idx].focus(); blocks[new_idx].scroll_visible()
            elif event.key == "x":
                if isinstance(focused, (CommandBlock, NoteBlock)): self.action_delete_block()
            elif event.key == "y":
                if isinstance(focused, NoteBlock):
                    self.yank_buffer = ("NOTE", focused.content)
                    self.notify("Note yanked")
                elif isinstance(focused, CommandBlock):
                    self.yank_buffer = ("CMD", focused.command, focused.cwd)
                    self.notify("Command yanked")
            elif event.key == "p": # Paste below
                if self.yank_buffer and focused in blocks:
                    new_block = self._create_block_from_yank()
                    container.mount(new_block, after=focused); new_block.focus()
            elif event.key == "P": # Paste above
                if self.yank_buffer and focused in blocks:
                    new_block = self._create_block_from_yank()
                    idx = container.children.index(focused)
                    container.mount(new_block, before=idx); new_block.focus()
            elif event.key == "e":
                if isinstance(focused, (CommandBlock, NoteBlock)): focused.toggle_edit()
            elif event.key == "j":
                if isinstance(focused, CommandBlock): focused.run_process()
            elif event.key == "ctrl+up": self.action_move_up()
            elif event.key == "ctrl+down": self.action_move_down()
            elif event.key == "escape":
                self.enter_normal_mode()

    def _create_block_from_yank(self):
        if not self.yank_buffer: return None
        if self.yank_buffer[0] == "NOTE":
            return NoteBlock(self.yank_buffer[1])
        else:
            return CommandBlock(self.yank_buffer[1], self.yank_buffer[2], self)

    @on(TextArea.Changed, "#main_input")
    def in_ch(self, event):
        txt = event.text_area.text

        if not self._suppress_search and self.query_one("#palette").has_class("visible"):
            self.update_palette(txt)
        self._suppress_search = False

    # --- CORE ACTIONS ---
    def action_submit(self):
        ta = self.query_one("#main_input"); text = ta.text
        mode = self.input_mode

        if not text.strip():
            self.enter_normal_mode(); return

        ta.text = ""; self.query_one("#palette").remove_class("visible")
        container = self.query_one("#command_history")

        if mode == "CMD":
            self.handle_internal_command(text.strip())
            self.enter_normal_mode()
            return

        if mode == "BASH":
            content = text.strip()
            self.history.add(content)
            new_block = CommandBlock(content, os.getcwd(), self)
            container.mount(new_block)
            self.call_after_refresh(new_block.run_process)
        elif mode == "NOTE":
            content = text.strip()
            new_block = NoteBlock(content); container.mount(new_block)
        else:
            self.notify("Unknown mode", severity="error")
            self.enter_normal_mode()
            return

        new_block.scroll_visible()
        self.enter_normal_mode()

    def handle_internal_command(self, cmd_line):
        parts = cmd_line.split(" ", 1)
        cmd = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "export": self.export_notebook(args or f"session_{int(time.time())}.md")
        elif cmd == "import": self.import_notebook(args)
        elif cmd == "exit": self.exit()
        elif cmd == "save_wf": self.action_save_wf_dialog()
        elif cmd == "clear":
            container = self.query_one("#command_history")
            for child in container.children[1:]: child.remove()
        elif cmd == "help":
            self.notify("Commands: export [file], import [file], exit, save_wf, clear, help")
        else:
            self.notify(f"Unknown command: {cmd}", severity="error")

    @work(exclusive=False, thread=True)
    def start_process(self, cmd: str, block: CommandBlock):
        m, s = pty.openpty()
        # Set some sane terminal size to avoid weird wrapping/numbers (columns, rows)
        try:
            import fcntl, termios, struct
            fcntl.ioctl(m, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        except: pass

        try:
            p = subprocess.Popen(cmd, shell=True, executable=BASH_EXE, stdout=s, stderr=s, stdin=s,
                                 close_fds=True, preexec_fn=os.setsid)
            self.active_processes.append(p); block.process = p; block.proc_active = True; os.close(s)
            while p.poll() is None:
                try:
                    data = os.read(m, 4096).decode(errors="replace")
                    if data: self.call_from_thread(block.append_output, data)
                except OSError: break
            self.call_from_thread(block.finish, p.wait())
        except Exception as e: self.call_from_thread(block.append_output, f"\nError: {e}")
        finally: 
            try: os.close(m)
            except: pass

    # --- EXPORT / IMPORT LOGIC ---
    def action_save_notebook_dialog(self):
        self.push_screen(SaveNotebookModal(), self.export_notebook)

    def action_import_notebook_dialog(self):
        self.push_screen(ImportNotebookModal(), self.import_notebook)

    def import_notebook(self, filename: str):
        if not filename or not os.path.exists(filename): return
        try:
            with open(filename, "r") as f: content = f.read()
            container = self.query_one("#command_history")
            for child in container.children[1:]: child.remove()

            # Match bash, sh, shell, or text blocks
            pattern = re.compile(r'```(bash|sh|shell|text)\n(.*?)\n```', re.DOTALL)
            last_pos = 0
            last_command_block = None

            matches = list(pattern.finditer(content))
            for match in matches:
                before = content[last_pos:match.start()].strip()
                if before:
                    # Filter out the generic header but keep other headers
                    lines = [l for l in before.splitlines() if not l.strip().startswith("# Shell Notebook Export")]
                    clean_before = "\n".join(lines).strip()
                    if clean_before:
                        # Split by headers for better granularity if possible
                        parts = re.split(r'(\n#+ .*)', "\n" + clean_before)
                        current_part = ""
                        for part in parts:
                            if part.strip():
                                if part.startswith("\n#"):
                                    if current_part.strip(): container.mount(NoteBlock(current_part.strip()))
                                    current_part = part
                                else:
                                    current_part += part
                        if current_part.strip(): container.mount(NoteBlock(current_part.strip()))

                lang, code = match.groups()
                if lang in ("bash", "sh", "shell"):
                    last_command_block = CommandBlock(code.strip(), os.getcwd(), self)
                    container.mount(last_command_block)
                elif lang == "text" and last_command_block:
                    last_command_block.full_output = code.strip()
                    try:
                        last_command_block.query_one("#output").update(Text.from_ansi(last_command_block.full_output))
                        last_command_block.query_one("#info").update("[blue]Imported[/]")
                    except: pass
                else:
                    # Treat unknown or orphaned text block as a NoteBlock
                    container.mount(NoteBlock(f"```text\n{code}\n```"))

                last_pos = match.end()

            after = content[last_pos:].strip()
            if after:
                lines = [l for l in after.splitlines() if not l.strip().startswith("# Shell Notebook Export")]
                clean_after = "\n".join(lines).strip()
                if clean_after: container.mount(NoteBlock(clean_after))
            self.notify(f"Importiert: {filename}", severity="information")
        except Exception as e:
            self.notify(f"Fehler beim Import: {e}", severity="error")

    def export_notebook(self, filename: str):
        if not filename: return
        container = self.query_one("#command_history")
        md_output = [f"# Shell Notebook Export - {time.strftime('%Y-%m-%d %H:%M:%S')}\n"]
        for widget in container.children:
            if isinstance(widget, NoteBlock):
                md_output.append(f"{widget.content}\n")
            elif isinstance(widget, CommandBlock):
                md_output.append(f"```bash\n{widget.command}\n```\n")

                if widget.full_output.strip():
                    # More comprehensive ANSI cleaning
                    ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
                    clean = ansi_escape.sub('', widget.full_output)
                    md_output.append(f"```text\n{clean.strip()}\n```\n")
        try:
            with open(filename, "w") as f: f.write("\n".join(md_output))
            self.notify(f"Gespeichert: {filename}", severity="information")
        except Exception as e: self.notify(f"Fehler: {e}", severity="error")

    def on_click(self, event: events.Click):
        try:
            widget, _ = self.screen.get_widget_at(event.screen_x, event.screen_y)
            node = widget
            while node:
                if isinstance(node, (CommandBlock, NoteBlock)):
                    now = time.time()
                    if now - node.last_click_time < 0.4:
                        self.query_one("#main_input").text = node.command if isinstance(node, CommandBlock) else node.content
                        self.query_one("#main_input").focus()
                    else: node.focus()
                    node.last_click_time = now; return
                node = node.parent
        except: pass

    def action_save_wf_dialog(self):
        self.push_screen(SaveWorkflowModal(self.query_one("#main_input").text), lambda s: s and setattr(self, 'workflows', load_workflows()))
    def action_move_up(self):
        container = self.query_one("#command_history")
        focused = self.focused
        if focused and isinstance(focused, (CommandBlock, NoteBlock)):
            idx = container.children.index(focused)
            if idx > 1: container.move_child(focused, before=idx-1)

    def action_move_down(self):
        container = self.query_one("#command_history")
        focused = self.focused
        if focused and isinstance(focused, (CommandBlock, NoteBlock)):
            idx = container.children.index(focused)
            if idx < len(container.children) - 1: container.move_child(focused, after=idx+1)

    def action_delete_block(self):
        focused = self.focused
        if focused and isinstance(focused, (CommandBlock, NoteBlock)):
            if isinstance(focused, CommandBlock) and focused.process:
                try: os.killpg(os.getpgid(focused.process.pid), signal.SIGTERM)
                except: pass
            focused.remove()
            self.notify("Block gelöscht", severity="information")
    def action_close_palette(self): self.query_one("#palette").remove_class("visible")
    def on_unmount(self): 
        self.history.save()
        for p in self.active_processes: 
            try: os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except: pass

if __name__ == "__main__": ShellApp().run()

