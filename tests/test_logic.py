import pytest
from unittest.mock import MagicMock
import os
import json
import asyncio
from client import ClientApp, NoteBlock, CommandBlock

def test_fuzzy_match_basics():
    from common import fuzzy_match
    assert fuzzy_match("abc", "a b c") is True
    assert fuzzy_match("abc", "def") is False
    assert fuzzy_match("", "any") is True

def test_history_manager(tmp_path):
    from common import HistoryManager
    import common
    history_file = tmp_path / "history.txt"
    common.HISTORY_FILE = str(history_file)

    hm = HistoryManager()
    hm.add("ls -la")
    hm.add("cd /tmp")
    hm.add("ls -la") # Duplicate

    assert len(hm.cache) == 2
    assert hm.cache[-1] == "ls -la"

@pytest.mark.asyncio
async def test_import_parsing():
    class DummyApp:
        def __init__(self):
            self.container = MagicMock()
            self.user_id = "test-user"
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

    assert len(blocks) >= 3
    assert any("Header 1" in b["content"] for b in blocks if b["type"] == "NOTE")
    assert any("echo \"hello world\"" in b["content"] for b in blocks if b["type"] == "CMD")

    if os.path.exists("test_import_complex.md"):
        os.remove("test_import_complex.md")
