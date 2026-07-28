import os
import sys
import re
import time
import termios
import tty
from typing import Optional, Tuple


def _luminance(r: int, g: int, b: int) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def query_terminal_colors(timeout: float = 0.15) -> dict:
    fd = sys.stdin.fileno()
    
    if not os.isatty(fd):
        return {"bg": None, "fg": None, "bg_is_dark": None}
    
    old = termios.tcgetattr(fd)
    new = old._replace(lflag=old.lflag & ~(termios.ECHO | termios.ICANON))
    result = {"bg": None, "fg": None, "bg_is_dark": None}

    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, list(new))

        os.write(fd, b"\x1b]11;?\x1b\\\x1b]10;?\x1b\\")
        os.flush(sys.stdout)

        import select
        response = b""
        deadline = time.time() + timeout

        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                response += chunk
                if b"\x07" in response or b"\x1b\\" in response:
                    break

        pattern = re.compile(rb"\x1b\](\d+);rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)(?:\x1b\\\\|\x07)")
        for match in pattern.finditer(response):
            code, r, g, b = match.groups()
            code = code.decode()
            r_int = int(r, 16) >> 8
            g_int = int(g, 16) >> 8
            b_int = int(b, 16) >> 8
            hex_color = _rgb_to_hex(r_int, g_int, b_int)

            if code == "11":
                result["bg"] = hex_color
                result["bg_is_dark"] = _luminance(r_int, g_int, b_int) < 128
            elif code == "10":
                result["fg"] = hex_color

    except Exception:
        pass
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, list(old))
        except Exception:
            pass

    return result


def derive_theme_colors(bg: str, fg: str) -> dict:
    bg_r, bg_g, bg_b = _hex_to_rgb(bg)
    fg_r, fg_g, fg_b = _hex_to_rgb(fg)
    is_dark = _luminance(bg_r, bg_g, bg_b) < 128

    def blend(c1: str, c2: str, t: float) -> str:
        r1, g1, b1 = _hex_to_rgb(c1)
        r2, g2, b2 = _hex_to_rgb(c2)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return _rgb_to_hex(r, g, b)

    if is_dark:
        surface = blend(bg, fg, 0.05)
        panel = blend(bg, fg, 0.08)
        primary = blend(bg, fg, 0.25)
        secondary = blend(bg, fg, 0.18)
        accent = blend(bg, fg, 0.35)
        success = "#00e676" if fg_r < 200 else "#00c853"
        error = "#ff5252" if fg_r < 200 else "#d32f2f"
        warning = "#ffab40" if fg_r < 200 else "#ff8f00"
    else:
        surface = blend(bg, fg, 0.08)
        panel = blend(bg, fg, 0.12)
        primary = blend(bg, fg, 0.30)
        secondary = blend(bg, fg, 0.22)
        accent = blend(bg, fg, 0.40)
        success = "#2e7d32" if fg_r > 100 else "#388e3c"
        error = "#c62828" if fg_r > 100 else "#d32f2f"
        warning = "#e65100" if fg_r > 100 else "#ef6c00"

    return {
        "bg_dark": bg,
        "bg_input": surface,
        "bg_block": panel,
        "bg_focus": blend(panel, fg, 0.15),
        "neptune_primary": primary,
        "neptune_dim": blend(bg, primary, 0.3),
        "neptune_bright": blend(primary, fg, 0.4),
        "text_main": fg,
        "text_dim": blend(fg, bg, 0.4),
        "success": success,
        "error": error,
        "border": blend(bg, primary, 0.5),
        "is_dark": is_dark,
    }


async def detect_terminal_theme() -> Optional[dict]:
    loop = None
    try:
        loop = __import__("asyncio").get_event_loop()
        colors = await loop.run_in_executor(
            None, lambda: query_terminal_colors(timeout=0.15)
        )
        if colors["bg"] and colors["fg"]:
            return derive_theme_colors(colors["bg"], colors["fg"])
    except Exception:
        pass
    return None
