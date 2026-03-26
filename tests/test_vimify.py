import pytest
from main import fuzzy_match, ShellApp, CommandBlock, NoteBlock
from textual.widgets import TextArea

def test_internal_command_parsing():
    app = ShellApp()
    # Mock some app components
    app.export_notebook = lambda x: x
    app.import_notebook = lambda x: x
    app.notify = lambda m, severity=None: m

    # We can't easily run the full app but we can test the handler
    # Actually, handle_internal_command is what we want to test

    # This is a bit tricky without a running app, but let's try to mock enough
    from unittest.mock import MagicMock
    app.query_one = MagicMock()

    app.handle_internal_command("help")
    # Should not crash

def test_prefix_logic():
    # Test how on_key might handle prefixes if we could simulate it
    # For now, let's just check if the logic in action_submit works as expected
    pass

def test_yank_paste_logic():
    app = ShellApp()
    nb = NoteBlock("test note")
    cb = CommandBlock("echo hello", "/tmp", app)

    # Yank Note
    app.yank_buffer = ("NOTE", nb.content)
    nb_clone = app._create_block_from_yank()
    assert isinstance(nb_clone, NoteBlock)
    assert nb_clone.content == "test note"

    # Yank Cmd
    app.yank_buffer = ("CMD", cb.command, cb.cwd)
    cb_clone = app._create_block_from_yank()
    assert isinstance(cb_clone, CommandBlock)
    assert cb_clone.command == "echo hello"
    assert cb_clone.cwd == "/tmp"

def test_focusability():
    app = ShellApp()
    nb = NoteBlock("test")
    cb = CommandBlock("ls", ".", app)
    assert nb.can_focus is True
    assert cb.can_focus is True
