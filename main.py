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
        self.is_collapsed = False
    def compose(self) -> ComposeResult:
        yield Button("/\\", id="toggle_expand", classes="toggle-expand-btn")
        yield Markdown(self.content, id="md_render", classes="markdown-content")
        yield TextArea(self.content, id="block_text_edit", classes="hidden", language="markdown")
        yield Label("[dim]Note (e: edit | ctrl+enter: save)[/]", classes="block-info")
    def toggle_edit(self):
        self.is_editing = not self.is_editing
        render, edit = self.query_one("#md_render"), self.query_one("#block_text_edit")
        if self.is_editing:
            render.add_class("hidden"); edit.remove_class("hidden"); edit.focus()
        else:
            self.content = edit.text
            render.update(self.content); render.remove_class("hidden"); edit.add_class("hidden")
    @on(Button.Pressed, "#toggle_expand")
    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        btn = self.query_one("#toggle_expand")
        if self.is_collapsed:
            self.add_class("collapsed")
            btn.label = "\\/"
        else:
            self.remove_class("collapsed")
            btn.label = "/\\"

    def on_key(self, event: events.Key):
        if not self.is_editing and event.key == "e": self.toggle_edit()
        elif self.is_editing and event.key == "ctrl+enter": self.toggle_edit()

class CommandBlock(Static):
    can_focus = True
    def __init__(self, command: str, cwd: str, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.command, self.cwd, self.app_ref = command, cwd, app_ref
        self.full_output, self.proc_active, self.process, self.is_editing, self.last_click_time = "", False, None, False, 0
        self.start_time = 0
        self.is_collapsed = False
    def compose(self) -> ComposeResult:
        yield Button("/\\", id="toggle_expand", classes="toggle-expand-btn")
        with Horizontal(classes="block-header"):
            yield Label("➜", classes="prompt-symbol")
            with Vertical():
                yield Label(f"[bold blue]{self.cwd}[/]", classes="cwd-label")
                yield Static(Syntax(self.command, "bash", theme="monokai"), id="cmd_syntax", classes="cmd-syntax")
            yield TextArea(self.command, id="block_text_edit", classes="hidden", language="bash")
        yield Static("", id="output", classes="block-output", markup=False)
        yield Label("[grey44]Ready[/]", id="info", classes="block-info")

    def update_status(self):
        if self.proc_active:
            elapsed = time.time() - self.start_time
            self.query_one("#info").update(f"[yellow]⏳ {elapsed:.1f}s[/]")
    def append_output(self, text: str):
        # Basic terminal emulation for interactive commands like 'watch'
        # \x1b[H (Home) or \x1b[2J (Clear Screen)
        if "\x1b[H" in text or "\x1b[2J" in text:
            idx = max(text.rfind("\x1b[H"), text.rfind("\x1b[2J"))
            self.full_output = text[idx:]
        else:
            # Filter out some more problematic control sequences
            # especially OSC sequences that might contain numbers and end with \x07 or \x1b\
            text = re.sub(r'\x1b\][0-9]*;.*?\x07', '', text)
            text = re.sub(r'\x1b\][0-9]*;.*?\x1b\\', '', text)
            self.full_output += text

        # Limit buffer to avoid performance issues
        if len(self.full_output) > 30000:
            self.full_output = "...(truncated)...\n" + self.full_output[-30000:]

        self.query_one("#output").update(Text.from_ansi(self.full_output))
    def finish(self, code: int):
        self.proc_active = False
        elapsed = time.time() - self.start_time
        status = "[green]✅ OK[/]" if code == 0 else f"[red]❌ ERR({code})[/]"
        self.query_one("#info").update(f"{status} [dim]({elapsed:.1f}s)[/]")
        self.remove_class("running")
    def toggle_edit(self):
        self.is_editing = not self.is_editing
        syntax, edit = self.query_one("#cmd_syntax"), self.query_one("#block_text_edit")
        if self.is_editing:
            syntax.add_class("hidden"); edit.remove_class("hidden"); edit.focus()
        else:
            self.command = edit.text
            syntax.update(Syntax(self.command, "bash", theme="monokai"))
            syntax.remove_class("hidden"); edit.add_class("hidden"); self.run_process()
    @on(Button.Pressed, "#toggle_expand")
    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        btn = self.query_one("#toggle_expand")
        if self.is_collapsed:
            self.add_class("collapsed")
            btn.label = "\\/"
        else:
            self.remove_class("collapsed")
            btn.label = "/\\"

    def run_process(self):
        self.full_output = ""; self.query_one("#output").update(""); self.add_class("running")
        self.start_time = time.time()
        self.app_ref.start_process(self.command, self)
    def on_key(self, event: events.Key):
        if not self.is_editing and event.key == "e": self.toggle_edit()
        elif self.is_editing and event.key == "ctrl+enter": self.toggle_edit()
        elif not self.is_editing and event.key == "ctrl+enter": self.run_process()
        elif not self.is_editing and event.key == "ctrl+c" and self.process:
            try: os.killpg(os.getpgid(self.process.pid), signal.SIGINT)
            except: pass

# --- APP ---

class ShellApp(App):
    CSS_PATH = THEME_FILE
    # Geänderte Bindings: Ctrl+E für Export, Ctrl+P für Palette (da Ctrl+P oft System-Print ist)
    BINDINGS = [
        Binding("ctrl+q", "quit", "Exit"),
        Binding("ctrl+n", "toggle_mode", "CMD/NOTE"),
        Binding("ctrl+enter", "submit", "Execute"),
        Binding("ctrl+s", "save_wf_dialog", "Save WF"),
        Binding("ctrl+e", "save_notebook_dialog", "Export MD"),
        Binding("ctrl+i", "import_notebook_dialog", "Import MD"),
        Binding("shift+up", "move_up", "Move Up"),
        Binding("shift+down", "move_down", "Move Down"),
        Binding("ctrl+x", "delete_block", "Delete Block"),
        Binding("escape", "close_palette", "Close")
    ]

    def __init__(self):
        super().__init__()
        self.history = HistoryManager()
        self.input_mode, self.active_processes, self._suppress_search = "CMD", [], False

    def compose(self) -> ComposeResult:
        yield Header()
        with ScrollableContainer(id="command_history"):
            yield Static("[bold magenta]Gemmi-Shell v12.0 | Notebook Chronicler[/]")
        yield OptionList(id="palette")
        with Vertical(id="input_area"):
            self.mode_label = Label("[bold cyan]MODE: COMMAND[/]", id="mode_indicator")
            yield self.mode_label
            yield TextArea(language="bash", id="main_input")
        yield Footer()

    def on_mount(self):
        self.workflows = load_workflows(); self.query_one("#main_input").focus()
        self.set_interval(0.5, self.update_running_statuses)

    def update_running_statuses(self):
        for widget in self.query_one("#command_history").children:
            if isinstance(widget, CommandBlock) and widget.proc_active:
                widget.update_status()

    def action_toggle_mode(self):
        self.input_mode = "NOTE" if self.input_mode == "CMD" else "CMD"
        c = "magenta" if self.input_mode == "NOTE" else "cyan"
        self.mode_label.update(f"[bold {c}]MODE: {self.input_mode}[/]")
        inp = self.query_one("#main_input")
        inp.language = "markdown" if self.input_mode == "NOTE" else "bash"
        # Force re-render of input if possible or just focus
        inp.focus()

    # --- PALETTE LOGIC ---
    def _get_current_token(self, text: str) -> str:
        if not text or text.endswith(" "): return ""
        parts = re.findall(r'(?:[^\s"\']|"(?:\\.|[^"])*"|\'(?:\\.|[^\'])*\')+', text)
        return parts[-1] if parts else ""

    def update_palette(self, val: str):
        p = self.query_one("#palette"); p.clear_options()
        if not val.strip() and not val.endswith(" "): p.remove_class("visible"); return
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
        if "[green]Path:[/]" in label:
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
        p, inp = self.query_one("#palette"), self.query_one("#main_input")
        if event.key == "ctrl+p": # Manuelles Triggern der Palette
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

    # --- CORE ACTIONS ---
    def action_submit(self):
        ta = self.query_one("#main_input"); content = ta.text.strip()
        if not content: return
        ta.text = ""; self.query_one("#palette").remove_class("visible")
        container = self.query_one("#command_history")
        if self.input_mode == "NOTE":
            new_block = NoteBlock(content); container.mount(new_block)
        else:
            self.history.add(content)
            if content.startswith("cd "):
                try:
                    os.chdir(os.path.expanduser(content[3:].strip() or "~"))
                    container.mount(Label(f"[dim]➜ {os.getcwd()}[/]")); return
                except: pass
            new_block = CommandBlock(content, os.getcwd(), self)
            container.mount(new_block); new_block.run_process()
        new_block.scroll_visible()

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
            pattern = re.compile(r'```(bash|text)\n(.*?)\n```', re.DOTALL)
            last_pos = 0
            last_command_block = None
            matches = list(pattern.finditer(content))
            for match in matches:
                before = content[last_pos:match.start()].strip()
                if before:
                    lines = [l for l in before.splitlines() if not l.strip().startswith("# Shell Notebook Export")]
                    clean_before = "\n".join(lines).strip()
                    if clean_before: container.mount(NoteBlock(clean_before))
                lang, code = match.groups()
                if lang == "bash":
                    last_command_block = CommandBlock(code, os.getcwd(), self)
                    container.mount(last_command_block)
                elif lang == "text" and last_command_block:
                    last_command_block.full_output = code
                    try:
                        last_command_block.query_one("#output").update(Text.from_ansi(code))
                        last_command_block.query_one("#info").update("[blue]Imported[/]")
                    except: pass
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

