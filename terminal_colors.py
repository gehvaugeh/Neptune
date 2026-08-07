import os
import sys
import re
import time
import termios
import tty
import logging
from typing import Optional, Tuple


def _luminance(r: int, g: int, b: int) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def query_terminal_colors(timeout: float = 0.5) -> dict:
    result = {"bg": None, "fg": None, "bg_is_dark": None}

    import select

    tty_fd = None
    try:
        tty_fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        pass

    if tty_fd is None:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            logging.debug("No TTY available for color query")
            return result
    else:
        fd = tty_fd

    old = termios.tcgetattr(fd)
    new = old._replace(lflag=old.lflag & ~(termios.ECHO | termios.ICANON))

    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, list(new))

        os.write(fd, b"\x1b]11;?\x1b\\\x1b]10;?\x1b\\")

        response = b""
        deadline = time.time() + timeout

        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            ready, _, _ = select.select([fd], [], [], min(remaining, 0.05))
            if ready:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                response += chunk
                has_bel = b"\x07" in response
                has_st = b"\x1b\\" in response
                if has_bel or has_st:
                    if response.count(b"\x07") + response.count(b"\x1b\\") >= 2:
                        break
                    if has_bel and has_st:
                        break

        pattern = re.compile(rb"\x1b\](\d+);rgba?:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)(?:/[0-9a-fA-F]+)?(?:\x1b\\|\x07)")
        for match in pattern.finditer(response):
            code, r, g, b = match.groups()
            code = code.decode()

            def _to_8bit(val: bytes) -> int:
                v = int(val, 16)
                if len(val) <= 2:
                    return v
                if len(val) == 3:
                    return v >> 4
                return v >> 8

            r_int = _to_8bit(r)
            g_int = _to_8bit(g)
            b_int = _to_8bit(b)
            hex_color = _rgb_to_hex(r_int, g_int, b_int)

            if code == "11":
                result["bg"] = hex_color
                result["bg_is_dark"] = _luminance(r_int, g_int, b_int) < 128
            elif code == "10":
                result["fg"] = hex_color

        logging.debug(f"OSC color query: bg={result['bg']}, fg={result['fg']} (from {len(response)}b response)")
    except Exception as e:
        logging.debug(f"OSC color query error: {e}")
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, list(old))
        except Exception:
            pass
        if tty_fd is not None:
            try:
                os.close(tty_fd)
            except OSError:
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
        primary = blend(bg, fg, 0.30)
        surface = blend(bg, fg, 0.04)
        panel = blend(bg, fg, 0.07)
        success = "#00e676"
        error = "#ff5252"
    else:
        primary = blend(bg, fg, 0.35)
        surface = blend(bg, fg, 0.06)
        panel = blend(bg, fg, 0.10)
        success = "#2e7d32"
        error = "#c62828"

    return {
        "primary": primary,
        "background": bg,
        "foreground": fg,
        "surface": surface,
        "panel": panel,
        "success": success,
        "error": error,
        "is_dark": is_dark,
    }


def detect_terminal_theme(timeout: float = 0.2) -> Optional[dict]:
    try:
        colors = query_terminal_colors(timeout=timeout)
        if colors["bg"] and colors["fg"]:
            return colors
    except Exception:
        pass
    return None
