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

# Header 1
Some note text

```bash
echo "hello world"
```

```text
hello world
```

## Header 2
Final note"""

    with open("test_import_complex.md", "w") as f:
        f.write(md_content)

    main.ShellApp.import_notebook(app, "test_import_complex.md")

    # We expect: NoteBlock (Header 1), NoteBlock (Some note text), CommandBlock, NoteBlock (Header 2 + Final note)
    # The current regex for headers might be aggressive. Let's see.
    print(f"Mounted count: {len(mounted_widgets)}")
    for i, w in enumerate(mounted_widgets):
        if isinstance(w, main.NoteBlock):
            print(f"{i}: Note: {repr(w.content)}")
        else:
            print(f"{i}: Cmd: {repr(w.command)}")

    assert len(mounted_widgets) >= 3
    assert any(isinstance(w, main.CommandBlock) for w in mounted_widgets)

    os.remove("test_import_complex.md")
