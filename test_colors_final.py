import re
import pyte
from rich.style import Style
from client import CommandBlock

class MockApp:
    def __init__(self):
        self.preferred_cols = 80
        self.preferred_rows = 24
        self.input_mode = "NORMAL"

def test_hex_colors():
    app = MockApp()
    block = CommandBlock("test", "ls", "/tmp", app)

    # Mock a character with 6-digit hex color
    char6 = pyte.screens.Char("X", fg="3b224c", bg="default")
    style6 = block._get_rich_style(char6)
    assert style6.color.name == "#3b224c"

    # Mock a character with 8-digit hex color
    char8 = pyte.screens.Char("Y", fg="default", bg="02040aFF")
    style8 = block._get_rich_style(char8)
    assert style8.bgcolor.name == "#02040a"

    # Mock invalid color
    char_inv = pyte.screens.Char("Z", fg="invalid", bg="default", bold=True)
    style_inv = block._get_rich_style(char_inv)
    assert style_inv.bold == True
    assert style_inv.color is None
    assert block._color_error == True

if __name__ == "__main__":
    try:
        test_hex_colors()
        print("Final color logic tests PASSED")
    except Exception as e:
        print(f"Final color logic tests FAILED: {e}")
        import traceback
        traceback.print_exc()
