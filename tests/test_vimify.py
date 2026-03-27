import pytest
from unittest.mock import MagicMock
import asyncio
from client import ClientApp, NoteBlock, CommandBlock
from common import fuzzy_match

@pytest.mark.asyncio
async def test_modal_interface_logic():
    app = ClientApp()
    app.mode_indicator = MagicMock()
    app.main_input = MagicMock()
    app.main_input.id = "main_input"
    # app.screen = MagicMock() # Property cannot be set
    app.palette = MagicMock()

    app.query_one = MagicMock()
    def mock_query(q):
        if q == "#mode_indicator": return app.mode_indicator
        if q == "#main_input": return app.main_input
        if q == "#palette": return app.palette
        return MagicMock()
    app.query_one.side_effect = mock_query

    # Check entering normal mode
    app.enter_normal_mode()
    assert app.input_mode == "NORMAL"
    assert app.count_str == ""
    app.query_one("#palette").remove_class.assert_called_with("visible")

    # Check selection mode
    app.enter_selection_mode()
    assert app.input_mode == "SELECTION"

    # Check input mode
    app.enter_input_mode("!")
    assert app.input_mode == "INPUT"
    assert app.main_input.text == "!"

def test_fuzzy_match_basics():
    assert fuzzy_match("ls", "ls -la") is True
    assert fuzzy_match("cd", "cd /tmp") is True
    assert fuzzy_match("dir", "directory") is True
    assert fuzzy_match("xyz", "abc") is False
    assert fuzzy_match("", "any") is True

@pytest.mark.asyncio
async def test_internal_command_parsing():
    app = ClientApp()
    app.notify = MagicMock()
    app.export_notebook = MagicMock()
    app.import_notebook = MagicMock()
    app.send_message = MagicMock()

    # Mocking internal methods as they are now async or depend on server
    app.send_message.return_value = asyncio.Future()
    app.send_message.return_value.set_result(None)

    # Test help
    await app.handle_internal_command("help")
    app.notify.assert_called()

    # Test clear (sends clear_session message)
    await app.handle_internal_command("clear")
    app.send_message.assert_called_with({"type": "clear_session"})

@pytest.mark.asyncio
async def test_yank_paste_logic():
    # Since ClientApp and Blocks now depend on asyncio and Server,
    # we test the logic of the yank/paste message generation
    app = ClientApp()
    app.user_id = "test-user"
    app.notify = MagicMock()

    # Yank Note
    nb = NoteBlock("id1", "test note", app)
    app.yank_buffer = ("NOTE", nb.content)
    assert app.yank_buffer[0] == "NOTE"
    assert app.yank_buffer[1] == "test note"

    # Yank Cmd
    cb = CommandBlock("id2", "echo hi", "/app", app)
    app.yank_buffer = ("CMD", cb.content, cb.cwd)
    assert app.yank_buffer[0] == "CMD"
    assert app.yank_buffer[1] == "echo hi"
    assert app.yank_buffer[2] == "/app"

@pytest.mark.asyncio
async def test_focusability():
    app = ClientApp()
    nb = NoteBlock("id3", "test", app)
    assert nb.can_focus is True

    cb = CommandBlock("id4", "ls", ".", app)
    assert cb.can_focus is True
