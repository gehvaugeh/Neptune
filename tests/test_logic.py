import os
import re
import pytest
from unittest.mock import MagicMock
import sys
from rich.text import Text

import main

def test_fuzzy_match():
    assert main.fuzzy_match("abc", "a b c") is True
    assert main.fuzzy_match("abc", "axbxc") is True
    assert main.fuzzy_match("abc", "cba") is False
    assert main.fuzzy_match("", "any") is True
    assert main.fuzzy_match("ANY", "any") is True

def test_history_manager(tmp_path):
    history_file = tmp_path / "history.txt"
    main.HISTORY_FILE = str(history_file)

    hm = main.HistoryManager()
    hm.add("ls")
    hm.add("cd /tmp")
    hm.add("ls") # Duplicate

    assert len(hm.cache) == 2
    assert hm.cache == ["cd /tmp", "ls"] # Most recent at the end

    matches = hm.get_matches("ls")
    assert "ls" in matches

    hm.save()
    assert history_file.exists()

    hm2 = main.HistoryManager()
    assert hm2.cache == ["cd /tmp", "ls"]

def test_import_parsing():
    class DummyApp:
        def query_one(self, q): return self.container
        def notify(self, m, severity=None): pass

    app = DummyApp()
    container = MagicMock()
    app.container = container

    mounted_widgets = []
    def mock_mount(w):
        mounted_widgets.append(w)
    container.mount = mock_mount
    container.children = [MagicMock()] # Header

    md_content = """# Shell Notebook Export - 2026-03-25 20:00:00

Some note text

```bash
echo "hello world"
```

```text
hello world
```

Final note"""

    with open("test_import_real.md", "w") as f:
        f.write(md_content)

    main.ShellApp.import_notebook(app, "test_import_real.md")

    assert len(mounted_widgets) == 3
    assert isinstance(mounted_widgets[0], main.NoteBlock)
    assert mounted_widgets[0].content == "Some note text"

    assert isinstance(mounted_widgets[1], main.CommandBlock)
    assert mounted_widgets[1].command == 'echo "hello world"'
    assert mounted_widgets[1].full_output == "hello world"

    assert isinstance(mounted_widgets[2], main.NoteBlock)
    assert mounted_widgets[2].content == "Final note"

    os.remove("test_import_real.md")

def test_get_current_token():
    class DummyApp:
        pass
    app = DummyApp()

    assert main.ShellApp._get_current_token(app, "ls -l /home") == "/home"
    assert main.ShellApp._get_current_token(app, "ls -l /home ") == ""
    assert main.ShellApp._get_current_token(app, 'ls "/home/user name"') == '"/home/user name"'
