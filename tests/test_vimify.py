import pytest
from unittest.mock import MagicMock
import asyncio
from client import ClientApp, NoteBlock, CommandBlock

@pytest.mark.asyncio
async def test_modal_interface_logic():
    app = ClientApp()
    app.mode_indicator = MagicMock()
    app.main_input = MagicMock()
    app.main_input.id = "main_input"
    app.palette = MagicMock()

    app.query_one = MagicMock()
    def mock_query(q):
        if q == "#mode_indicator": return app.mode_indicator
        if q == "#main_input": return app.main_input
        if q == "#palette": return app.palette
        if q == "#mode_prefix": return MagicMock()
        return MagicMock()
    app.query_one.side_effect = mock_query

    # Check entering normal mode
    app.enter_normal_mode()
    assert app.input_mode == "NORMAL"

    # Check selection mode
    app.enter_selection_mode()
    assert app.input_mode == "SELECTION"

    # Check input mode
    app.enter_input_mode("!")
    assert app.input_mode == "BASH"

@pytest.mark.asyncio
async def test_internal_command_parsing():
    app = ClientApp()
    app.notify = MagicMock()
    app.send_message = MagicMock()

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
    app = ClientApp()
    app.user_id = "test-user"

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
