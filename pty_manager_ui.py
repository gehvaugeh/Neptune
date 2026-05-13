import asyncio
from typing import Dict, List, Optional
from textual.app import ComposeResult
from textual.widgets import Label, Input, Button, OptionList, Static
from textual.widgets.option_list import Option
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual import on, events, message
from common import fuzzy_match

class RemotePTYAuthModal(ModalScreen):
    def __init__(self, host: str = "", user: str = "", key_path: str = "~/.ssh/id_rsa"):
        super().__init__()
        self.host = host
        self.user = user
        self.key_path = key_path

    def on_mount(self):
        if not self.host or not self.user:
            try: self.query_one("#auth_host_user").focus()
            except: pass
        else:
            try: self.query_one("#auth_key").focus()
            except: pass

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_dialog"):
            yield Label(f"[bold cyan]New Remote PTY[/]")
            if self.host and self.user:
                yield Label(f"Host: [white]{self.user}@{self.host}[/]")
            else:
                yield Input(placeholder="user@host", id="auth_host_user")
            with Horizontal(id="auth_type_row", classes="modal-row"):
                yield Label("Auth: ")
                yield Button("Key", id="toggle_auth", variant="primary")
            yield Input(value=self.key_path, placeholder="Key path...", id="auth_key")
            yield Input(placeholder="Password...", password=True, id="auth_pass", classes="hidden")
            with Horizontal(id="modal_buttons"):
                yield Button("Cancel", variant="error", id="cancel")
                yield Button("OK", variant="success", id="ok")

    @on(Button.Pressed, "#toggle_auth")
    def toggle_auth(self):
        btn = self.query_one("#toggle_auth")
        key_inp = self.query_one("#auth_key")
        pass_inp = self.query_one("#auth_pass")
        if btn.label == "Key":
            btn.label = "Password"
            key_inp.add_class("hidden")
            pass_inp.remove_class("hidden")
            pass_inp.focus()
        else:
            btn.label = "Key"
            key_inp.remove_class("hidden")
            pass_inp.add_class("hidden")
            key_inp.focus()

    @on(Button.Pressed, "#cancel")
    def cancel(self): self.dismiss(None)

    @on(Button.Pressed, "#ok")
    def ok(self):
        is_key = self.query_one("#toggle_auth").label == "Key"
        val = self.query_one("#auth_key").value if is_key else self.query_one("#auth_pass").value

        host_user = {}
        if not self.host or not self.user:
            raw = self.query_one("#auth_host_user").value
            if "@" in raw:
                u, h = raw.split("@", 1)
                host_user = {"user": u, "host": h}
            else:
                self.app.notify("Invalid user@host", severity="error")
                return
        else:
            host_user = {"user": self.user, "host": self.host}

        self.dismiss({"method": "key" if is_key else "password", "value": val, **host_user})

    @on(Input.Submitted, "#auth_host_user")
    @on(Input.Submitted, "#auth_key")
    @on(Input.Submitted, "#auth_pass")
    def on_submit(self): self.ok()

class ConfirmKillModal(ModalScreen):
    def __init__(self, pty_name: str):
        super().__init__()
        self.pty_name = pty_name

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_dialog"):
            yield Label(f"[bold red]WARNING: Kill PTY '{self.pty_name}'?[/]")
            yield Label("This PTY has running blocks. Killing it will stop all processes.")
            with Horizontal(id="modal_buttons"):
                yield Button("Cancel", variant="primary", id="cancel")
                yield Button("Kill All", variant="error", id="kill")

    @on(Button.Pressed, "#cancel")
    def cancel(self): self.dismiss(False)
    @on(Button.Pressed, "#kill")
    def kill(self): self.dismiss(True)

class RenamePTYModal(ModalScreen):
    def __init__(self, old_name: str):
        super().__init__()
        self.old_name = old_name

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_dialog"):
            yield Label("[bold cyan]Rename PTY[/]")
            yield Input(value=self.old_name, id="new_name")
            with Horizontal(id="modal_buttons"):
                yield Button("Cancel", variant="error", id="cancel")
                yield Button("Rename", variant="success", id="rename")

    def on_mount(self):
        self.query_one("#new_name").focus()

    @on(Button.Pressed, "#cancel")
    def cancel(self): self.dismiss(None)
    @on(Button.Pressed, "#rename")
    def rename(self): self.dismiss(self.query_one("#new_name").value)

    @on(Input.Submitted, "#new_name")
    def on_submit(self): self.rename()

class PTYManagerModal(ModalScreen):
    def __init__(self, ptys: Dict[int, Dict], default_pty_uid: int):
        super().__init__()
        self.ptys = ptys
        self.default_pty_uid = default_pty_uid
        self.search_query = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_dialog", classes="pty-manager-modal"):
            yield Label("[bold cyan]PTY Manager[/]")
            yield Input(placeholder="Search PTYs...", id="manager_search")
            yield OptionList(id="pty_list")
            yield Label("[dim]Enter: Select | x: Delete | r: Rename | n: New Local | N: New Remote | Esc: Close[/]", classes="modal-footer")

    def on_mount(self):
        self.update_list()
        self.query_one("#manager_search").focus()

    def update_list(self):
        ol = self.query_one("#pty_list")
        current_highlight = ol.highlighted
        ol.clear_options()

        items = []
        # Sort by UID
        for uid in sorted(self.ptys.keys()):
            info = self.ptys[uid]
            is_default = uid == self.default_pty_uid
            status = info.get("status", "idle")
            blocks = info.get("block_count", 0)
            name = info.get("name", f"pty-{uid}")

            icon = "●" if is_default else "○"
            if status == "running": icon = "⟳"

            display = f"{icon} [bold]ID:{uid:<2}[/] {name:<15} ({status:<8}) {blocks} blocks"
            if is_default: display += " [dim](default)[/]"

            if not self.search_query or fuzzy_match(self.search_query, f"{uid} {name}"):
                items.append(Option(display, id=str(uid)))

        # Always ensure something is highlighted if list not empty
        if items and ol.highlighted is None:
             ol.highlighted = 0

        for item in items:
            ol.add_option(item)

        if current_highlight is not None:
            ol.highlighted = min(current_highlight, ol.option_count - 1) if ol.option_count > 0 else None

    @on(Input.Changed, "#manager_search")
    def on_search(self, event: Input.Changed):
        self.search_query = event.value
        self.update_list()

    def on_key(self, event: events.Key):
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            ol = self.query_one("#pty_list")
            if ol.highlighted is not None:
                uid_str = ol.get_option_at_index(ol.highlighted).id
                if uid_str:
                    self.dismiss({"action": "select", "uid": int(uid_str)})
            event.stop()
        elif event.key == "x":
            ol = self.query_one("#pty_list")
            if ol.highlighted is not None:
                uid_str = ol.get_option_at_index(ol.highlighted).id
                if uid_str:
                    uid = int(uid_str)
                    if uid == 0:
                        self.app.notify("This is the default pty and cannot be deleted", severity="warning")
                    else:
                        info = self.ptys[uid]
                        if info.get("block_count", 0) > 0 or info.get("status") == "running":
                            self.app.push_screen(ConfirmKillModal(info.get("name")),
                                lambda res, u=uid: self._do_delete(u) if res else None)
                        else:
                            self._do_delete(uid)
            event.stop()
        elif event.key == "r":
            ol = self.query_one("#pty_list")
            if ol.highlighted is not None:
                uid_str = ol.get_option_at_index(ol.highlighted).id
                if uid_str:
                    uid = int(uid_str)
                    self.app.push_screen(RenamePTYModal(self.ptys[uid].get("name")),
                        lambda res, u=uid: self._do_rename(u, res) if res else None)
            event.stop()
        elif event.key == "n":
            self.dismiss({"action": "new_local"})
            event.stop()
        elif event.key == "N":
            self.dismiss({"action": "new_remote"})
            event.stop()

    def _do_delete(self, uid):
        # We can't directly communicate with server from here easily without app ref
        # but we can dismiss with the action
        self.dismiss({"action": "delete", "uid": uid})

    def _do_rename(self, uid, new_name):
        self.dismiss({"action": "rename", "uid": uid, "name": new_name})
