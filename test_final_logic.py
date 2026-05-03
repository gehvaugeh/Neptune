import re
from rich.style import Style
from dataclasses import dataclass

@dataclass
class Char:
    data: str
    fg: str
    bg: str
    bold: bool = False
    italics: bool = False
    underscore: bool = False
    reverse: bool = False

class MockCommandBlock:
    def __init__(self):
        self._style_cache = {}
        self._color_error = False
        self._last_status_text = "Ready"

    def _get_rich_style(self, char):
        cache_key = (char.fg, char.bg, char.bold, char.italics, char.underscore, char.reverse)
        if cache_key in self._style_cache:
            return self._style_cache[cache_key]

        def map_color(c):
            if not c or c == "default": return None
            mapping = {
                "brown": "yellow",
                "lightgray": "white",
                "darkgray": "bright_black",
            }
            if isinstance(c, str):
                c = mapping.get(c, c)
                if c.startswith("bright"):
                    c = c.replace("bright", "bright_")
                if re.fullmatch(r"[0-9a-fA-F]{6}|[0-9a-fA-F]{8}", c):
                    return f"#{c[:6]}"
            return c

        fg = map_color(char.fg)
        bg = map_color(char.bg)

        try:
            parts = []
            if fg: parts.append(fg if (not isinstance(fg, str) or not fg.isdigit()) else f"color({fg})")
            if bg: parts.append(f"on {bg}" if (not isinstance(bg, str) or not bg.isdigit()) else f"on color({bg})")
            if char.bold: parts.append("bold")
            if char.italics: parts.append("italic")
            if char.underscore: parts.append("underline")
            if char.reverse: parts.append("reverse")

            style = Style.parse(" ".join(parts))
        except Exception as e:
            # print(f"Error parsing style: {e}")
            self._color_error = True
            parts = []
            if char.bold: parts.append("bold")
            if char.italics: parts.append("italic")
            if char.underscore: parts.append("underline")
            if char.reverse: parts.append("reverse")
            style = Style.parse(" ".join(parts)) if parts else Style.null()

        self._style_cache[cache_key] = style
        return style

block = MockCommandBlock()
test_chars = [
    Char("A", "3b224c", "default"),
    Char("B", "default", "02040a"),
    Char("C", "ff0000ff", "00ff00ff", bold=True), # 8-digit hex
    Char("D", "invalid", "default"),
    Char("E", "red", "blue", italics=True),
]

for c in test_chars:
    s = block._get_rich_style(c)
    print(f"Char data={c.data} fg={c.fg} bg={c.bg} -> style='{s}' color_error={block._color_error}")
