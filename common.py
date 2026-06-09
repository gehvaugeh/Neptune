import os
import json
import random
import shutil
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_FILE = os.path.join(BASE_DIR, "termux_workflows.json")
HISTORY_FILE = os.path.join(BASE_DIR, "history.txt")
REMOTE_HOSTS_FILE = os.path.join(BASE_DIR, "remote_hosts.txt")
THEME_FILE = os.path.join(BASE_DIR, "theme.css")

_ANSI_STRIP = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')
def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from a string."""
    return _ANSI_STRIP.sub('', text)

def get_shell():
    env_shell = os.environ.get("SHELL")
    if env_shell and shutil.which(env_shell):
        return env_shell
    termux_bash = "/data/data/com.termux/files/usr/bin/bash"
    if os.path.exists(termux_bash):
        return termux_bash
    return shutil.which("bash") or shutil.which("sh") or "/bin/sh"

def get_random_bright_color():
    colors = ["cyan", "magenta", "yellow", "green", "blue", "red", "orange", "springgreen"]
    return random.choice(colors)

def fuzzy_match(query: str, target: str) -> bool:
    if not query: return True
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
        if not query: return self.cache[-15:]
        return [c for c in self.cache if fuzzy_match(query, c)][-15:]
