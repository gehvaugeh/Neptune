import pytest
from unittest.mock import MagicMock
import os
import json
import asyncio
from client import ClientApp, NoteBlock, CommandBlock
import common as main

def test_fuzzy_match():
    assert main.fuzzy_match("abc", "a b c") is True
    assert main.fuzzy_match("abc", "def") is False
    assert main.fuzzy_match("", "any") is True
    assert main.fuzzy_match("longquery", "short") is False

def test_history_manager(tmp_path):
    history_file = tmp_path / "history.txt"
    main.HISTORY_FILE = str(history_file)

    hm = main.HistoryManager()
    hm.add("ls -la")
    hm.add("cd /tmp")
    hm.add("ls -la") # Duplicate

    assert len(hm.cache) == 2
    assert hm.cache[-1] == "ls -la"

    hm.save()
    assert os.path.exists(str(history_file))

    hm2 = main.HistoryManager()
    assert len(hm2.cache) == 2

    matches = hm2.get_matches("ls")
    assert "ls -la" in matches

@pytest.mark.asyncio
async def test_import_parsing():
    class DummyApp:
        def __init__(self):
            self.container = MagicMock()
            self.user_id = "test-user"
            self.writer = MagicMock()
        def query_one(self, q): return self.container
        def notify(self, m, severity=None): pass
        async def send_message(self, msg):
            self.last_msg = msg

    app = DummyApp()

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

    await ClientApp.import_notebook(app, "test_import_complex.md")

    assert app.last_msg["type"] == "import_blocks"
    blocks = app.last_msg["blocks"]

    # Expected:
    # 1. NOTE: "# Header 1\nSome note text"
    # 2. CMD: "echo \"hello world\"", output: "hello world"
    # 3. NOTE: "## Header 2\nFinal note"

    assert len(blocks) >= 3
    assert any("Header 1" in b["content"] for b in blocks if b["type"] == "NOTE")
    assert any("echo \"hello world\"" in b["content"] for b in blocks if b["type"] == "CMD")
    assert any("hello world" in b["output"] for b in blocks if b["type"] == "CMD")
    assert any("Header 2" in b["content"] for b in blocks if b["type"] == "NOTE")

    if os.path.exists("test_import_complex.md"):
        os.remove("test_import_complex.md")
