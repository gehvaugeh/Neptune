# Neptune TUI Reference

Comprehensive guide for interacting with the Neptune terminal UI via tmux and the NeptuneOracle test framework.

## Quick Start

```bash
# Start
cd /home/vangegcz/coding/Neptune
python3 main.py all --clean-history -s test.sock

# Stop (inside Neptune)
:q!<Enter>

# or kill + clean
kill -9 $(ps aux | grep python3 | grep -v grep | grep -v networkd | grep -v unattended | grep -v spectrum | awk '{print $2}') 2>/dev/null
rm -f test.sock

# Visual check via tmux
tmux send-keys -t neptune '<keys>' Enter
sleep 1 && tmux capture-pane -t neptune -p

# Run blackbox tests
python3 tests/blackbox/run_blackbox_tests.py

# Interactive REPL for key discovery
python3 tests/oracle/test_driver.py --repl
```

## Mode System

Neptune has 8 modes. Think of NORMAL as the "hub" — almost all transitions go through it.

```
                         ┌──────────────┐
                  ┌──────┤    NORMAL    ├──────┐
                  │      │  (Hub/Idle)  │      │
                  │      └──────┬───────┘      │
             ────►│            │               │◄────
         ┌────────┴──┐  :  ┌───┴────┐    ┌────┴────────┐
         │  BASH !   │────►│ CMD :  │    │  SELECTION  │
         │ (shell)   │◄────│(intern)│    │ s (vim-like)│
         └──┬───┬────┘  Esc└───┬────┘    └──────┬───────┘
       Enter│   │TUI-Cmd      │Enter        e    │i  x/j/y/p
            │   ▼             ▼                 ▼   ▼   ────
            │ CONTROL     NORMAL           BLOCKEDIT CONTROL
            │ (dbl Esc ──► NORMAL)

   !! ──► PTY Target Bar (INPUT mode) ──► BASH auf Ziel-PTY
   !N  ──► BASH direkt auf PTY #N
```

### Mode Table

| Mode | Trigger | Prefix | Farbe | Verhalten |
|------|---------|--------|-------|-----------|
| NORMAL | (default) | – | `#757575` | Idle; Tasten = Keybindings |
| BASH | `!` / `!N` / `!!→target` | `!` | `#00e676` | Shell-Befehl eingeben; bleibt nach Enter in BASH |
| CMD | `:` | `:` | `#7c4dff` | Interne Kommandos; geht nach Enter zurück zu NORMAL |
| NOTE | `;` | `;` | `#ff5252` | Markdown-Notiz; bleibt nach Enter in NOTE |
| SELECTION | `s` (in NORMAL) | – | `#00b0ff` | Vim-like Block-Navigation |
| INPUT | `!!` (PTY Target Bar) | – | `#7c4dff` | Freitext für PTY-Ziel |
| BLOCKEDIT | `e` (in SELECTION) | – | `#ffab40` | Inline-Block bearbeiten; Esc=abbrechen, C-j=speichern |
| CONTROL | `i` (in SELECTION, auf TUI-Block) | – | `#f44336` | Interaktive TUI (vim/htop); Doppel-Esc→NORMAL |

### Mode-Übergänge im Detail

| Ausgang | Aktion | Ziel | Anmerkung |
|---------|--------|------|-----------|
| NORMAL | `!` drücken | BASH | 0.3s delay (wartet auf zweiten `!`) |
| NORMAL | `!!` innerhalb 0.3s | INPUT | PTY Target Bar öffnet sich |
| NORMAL | `!N` (Ziffer nach Bang) | BASH | Direkt PTY #N target |
| NORMAL | `:` drücken | CMD | |
| NORMAL | `;` drücken | NOTE | |
| NORMAL | `s` drücken | SELECTION | |
| NORMAL | `C-t` drücken | (Modal) | PTY Manager öffnet |
| NORMAL | `C-f` drücken | (Filter) | Filter Bar |
| BASH | `Enter` (submit) | BASH | Bleibt im Mode für nächsten Befehl |
| BASH | TUI-Cmd erkannt | CONTROL | Automatisch bei vim/htop/less/... |
| BASH | `Esc` | NORMAL | Oder SELECTION wenn `was_in_selection_mode` |
| CMD | `Enter` (submit) | NORMAL | Command wird ausgeführt |
| CMD | `Esc` | NORMAL | |
| NOTE | `Enter` (submit) | NOTE | Bleibt im Mode |
| NOTE | `Esc` | NORMAL | |
| SELECTION | `Esc` | NORMAL | |
| SELECTION | `:` / `;` / `!` / `!!` | CMD/NOTE/BASH | `was_in_selection_mode = True` |
| SELECTION | `e` (auf Block) | BLOCKEDIT | |
| SELECTION | `i` (auf TUI-Block) | CONTROL | |
| BLOCKEDIT | `Esc` | SELECTION/NORMAL | Ohne Speichern |
| BLOCKEDIT | `C-j` | SELECTION/NORMAL | Mit Speichern |
| CONTROL | `Esc` × 2 innerhalb 0.5s | NORMAL | Oder SELECTION wenn `was_in_selection` |
| INPUT | `Enter` (submit) | BASH | PTY Target wird aufgelöst |
| INPUT | `Esc` | NORMAL | Target Bar schließt |

### was_in_selection_mode Flag

Wenn man aus SELECTION heraus `:`, `;` oder `!` drückt, merkt sich Neptune das. Nach submit oder Esc kehrt man zurück zu SELECTION (statt NORMAL). Ermöglicht Workflow: Block auswählen → `!cmd` → Befehl ausführen → automatisch zurück zur Auswahl.

## Keybindings (alle Modes)

### Global

| Key | Aktion |
|-----|--------|
| `C-q` | Quit (mit Unsaved-Changes-Check) |
| `C-f` | Filter Bar ein/aus |
| `C-g` | Filter entfernen |
| `C-t` | PTY Manager öffnen |
| `Esc` | Kontextabhängig zurück (Mode beenden, Dropdown schließen, Modal schließen) |

### NORMAL Mode

| Key | Aktion |
|-----|--------|
| `!` | BASH mode (0.3s delay für `!!`) |
| `!!` | PTY Target Bar |
| `!N` (Ziffer) | BASH auf PTY #N |
| `:` | CMD mode |
| `;` | NOTE mode |
| `s` | SELECTION mode |
| `C-p` | Command Palette |

### SELECTION Mode (vim-like Block-Navigation)

| Key | Aktion |
|-----|--------|
| `j` / `Down` / `↑` | Nächster Block (×N mit Ziffern-Präfix) |
| `k` / `Up` / `↓` | Vorheriger Block (×N mit Ziffern-Präfix) |
| `x` | Block löschen |
| `r` | Block neu ausführen (CommandBlock) |
| `c` | PTY des Blocks wechseln |
| `y` | Block-Inhalt yanken (copy) |
| `p` | Nach fokussiertem Block einfügen |
| `P` | Vor fokussiertem Block einfügen |
| `z` | Block zoomen |
| `e` | Block editieren |
| `i` | CONTROL mode (TUI-App starten) |
| `C-s` | Block als Workflow speichern |
| `C-up` / `Alt-up` | Block nach oben verschieben |
| `C-down` / `Alt-down` | Block nach unten verschieben |
| `C-j` / `Enter` | Block neu ausführen (CommandBlock) |
| `:` | CMD mode |
| `;` | NOTE mode |
| `!` | BASH mode |
| `!!` | PTY Target Bar |
| `C-p` | Command Palette |
| `0-9` | Zähler-Akku (für `5j` = 5 Blöcke runter) |

### BASH / CMD / NOTE / INPUT Mode (Eingabe-Modes)

| Key | Aktion |
|-----|--------|
| `Enter` | Absenden (submit) |
| `C-Enter` / `S-Enter` / `C-j` / `C-m` | Zeilenumbruch (BASH/NOTE) |
| `Tab` | Autocomplete-Palette öffnen / Auswahl übernehmen |
| `Up` / `Down` | Palette navigieren (wenn sichtbar) |
| `C-p` | Palette togglen (wenn versteckt) |
| `C-s` | Workflow speichern (BASH) |
| `Esc` | Mode beenden |

### CONTROL Mode

Alle Tasten werden als ANSI-Sequenzen zum Server durchgereicht:

| Key | ANSI |
|-----|------|
| `Enter` | `\r` |
| `Backspace` | `\x7f` |
| `Tab` | `\t` |
| `Esc` | `\x1b` |
| `Up/Down/Left/Right` | `\x1b[A` / `[B` / `[C` / `[D` |
| `Home/End` | `\x1b[H` / `\x1b[F` |
| `PgUp/PgDn` | `\x1b[5~` / `\x1b[6~` |
| `Del` | `\x1b[3~` |
| `C-a` bis `C-z` | `chr(N-96)` |
| `C-[` | `\x1b` (Esc) |
| Doppel-Esc (0.5s) | CONTROL beenden |

## CMD-Befehle (`:`)

| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `:ptyman` | – | PTY Manager öffnen |
| `:export` | `[file] [no-output]` | Session als Markdown exportieren |
| `:import` | `<file> [no-output]` | Markdown importieren |
| `:exit` | – | Beenden (mit Unsaved-Check) |
| `:save_wf` | – | Aktuelle Eingabe als Workflow speichern |
| `:clear` | – | Alle Blöcke löschen, Server-Reset |
| `:help` | – | Hilfe anzeigen |

## PTY System

### PTY Manager (`C-t` oder `:ptyman`)

| Taste | Aktion |
|-------|--------|
| `n` | Neue lokale PTY |
| `N` | Neue remote PTY (SSH) |
| `x` | PTY löschen (mit Bestätigung bei running blocks) |
| `r` | PTY umbenennen |
| `/` | Search-Fokus |
| `Enter` / Klick | PTY auswählen (wird default) |

### PTY Target Bar (`!!`)

| Eingabe | Resultat |
|---------|----------|
| `0`, `1`, ... (UID) | Wechsel zu PTY #N |
| `local-0` (Name) | Wechsel zu gematchter PTY |
| `local` | Neue lokale PTY erstellen |
| `user@host` | Remote PTY Auth Modal → neue remote PTY |
| `user@host:port` | Mit Port |
| `user@host:port:key` | Direkt mit Key (kein Modal) |

### `!N` Syntax (Schnell-Wechsel)

| Eingabe | Resultat |
|---------|----------|
| `!` | BASH auf Default-PTY |
| `!0` | BASH auf PTY #0 |
| `!2` | BASH auf PTY #2 |

## Modal-Referenz

| Modal | Trigger | Wichtigste Elemente | Dismiss-Result |
|-------|---------|-------------------|----------------|
| PTYManagerModal | `C-t`, `:ptyman` | `#pty_list` (OptionList), `#manager_search` | `{"action":"select","uid":N}` oder `None` |
| RemotePTYAuthModal | `N` im PTY-Manager, `!!user@host` | `#auth_host_user`, `#auth_port`, `#auth_toggle`, `#auth_key`/`#auth_pass`, `#host_history_list`, `#key_list` | `{"method","value","port","user","host"}` oder `None` |
| SaveNotebookModal | `:export`, Palette | `#file_name`, `#include_toggle` | `(filename, include_output)` oder `None` |
| ImportNotebookModal | `:import`, Palette | `#file_name`, `#include_toggle` | `(filename, include_output)` oder `None` |
| SaveWorkflowModal | `C-s` (BASH), `:save_wf` | `#wf_name`, `#wf_cmd` (TextArea) | `(name, command)` oder `None` |
| ExitConfirmModal | `C-q` (unsaved) | `#no_exit`, `#cancel` | `"exit"` oder `None` |
| ConfirmKillModal | `x` auf laufender PTY | `#kill`, `#cancel` | `True` oder `False` |
| RenamePTYModal | `r` im PTY-Manager | `#new_name` | Neuer Name (str) oder `None` |

### Modal-Interaktion

- **Tab / Shift+Tab**: durch fokussierbare Elemente navigieren
- **Enter**: fokussierten Button aktivieren / Input submit
- **Esc**: Modal schließen (entspricht Cancel)
- **Dropdowns**: Tab auf markierten Eintrag übernimmt ihn; Pfeiltasten navigieren

## TUI-Commands (automatischer CONTROL mode)

Wenn der erste Token eines BASH-Befehls in dieser Liste ist, wechselt Neptune automatisch in CONTROL mode:

```
vim, vi, nano, emacs, htop, top, btm, less, more,
man, tmux, screen, neptune, sudo, su, passwd
```

Nach Beenden der App (Doppel-Esc) kehrst du zurück.

## Test-Framework (NeptuneOracle)

### Import & Setup

```python
import sys, os, time
sys.path.append("tests/oracle")
from test_driver import NeptuneOracle

def test_my_feature():
    oracle = NeptuneOracle("python3 main.py all --clean-history -s test.sock")
    try:
        oracle.wait_for_idle(5.0)

        # Interaktion
        oracle.send_input("<esc><esc>!echo 'hello' <return>")

        # Assertion mit Retry-Loop
        found = False
        for _ in range(10):
            oracle.feed_stream()
            if "hello" in oracle.get_screen_snapshot():
                found = True
                break
            time.sleep(0.5)
        assert found, "Feature failed!"
    finally:
        oracle.child.terminate(force=True)
```

### `send_input()` Syntax

| Syntax | Bedeutung |
|--------|-----------|
| `"<esc>"` | Escape |
| `"<enter>"` / `"<return>"` | Enter (CR) |
| `"<tab>"` | Tab |
| `"<up>"` / `"<down>"` / `"<left>"` / `"<right>"` | Pfeiltasten |
| `"<ctrl+up>"` | Ctrl+Pfeil hoch |
| `"<alt+down>"` | Alt+Pfeil runter |
| `"<ctrl+p>"` | Ctrl+P |
| `"!echo hi"` | Mode-Charaktere werden direkt mit 0.5s Delay gesendet |
| `"'literal'"` | In Anführungszeichen: roher String |
| `"action1, action2"` | Komma-getrennte Sequenz (mit 0.1s Pause) |

### Wichtige NeptuneOracle-Methoden

| Methode | Beschreibung |
|---------|--------------|
| `send_input(str)` | Sendet Tasten/Mode-Trigger |
| `wait_for_idle(sec=0.5)` | Fixed Sleep + feed_stream |
| `feed_stream()` | Liest child-output in pyte-Buffer |
| `get_screen_snapshot()` | Gibt aktuellen Screen als String zurück |
| `child.terminate(force=True)` | Killt den Prozess |

### Typische Test-Sequenzen

```python
# Mode wechseln
"<esc><esc>"                    # Sicher in NORMAL
"!echo test <return>"           # BASH: Befehl ausführen
":clear <return>"               # CMD: clear
";My Note <return>"             # NOTE: Notiz erstellen
"s"                             # SELECTION mode
"x"                             # Block löschen (in SELECTION)

# Autocomplete
"!ec<tab>"                      # Tab öffnet Palette
"<down>"                        # In Palette navigieren
"<enter>"                       # Auswahl übernehmen

# PTY Manager
"<esc><esc><ctrl+t>"            # PTY Manager öffnen
":ptyman <return>"              # via CMD

# Block reorder (SELECTION mode)
"<ctrl+up>"                     # Block nach oben
"<ctrl+down>"                   # Block nach unten

# Yank + Paste (SELECTION mode)
"y"                             # Yank
"<esc><esc>p"                   # NORMAL → Paste
```

## Wichtige Dateien

| Datei | Inhalt |
|-------|--------|
| `main.py` | Einstiegspunkt |
| `client.py` | TUI-Logik, Modes, Keybindings |
| `server.py` | Backend-Server |
| `pty_manager_ui.py` | PTY Manager Modal + Auth Modal |
| `theme.css` | TUI-Styling |
| `common.py` | TUI_CMDS, HistoryManager, Farben |
| `autocomplete.py` | Autocomplete-Provider |
| `markdown_toolbox.py` | NOTE-Markdown-Palette |
| `tests/oracle/test_driver.py` | NeptuneOracle (Test-Treiber) |
| `tests/blackbox/run_blackbox_tests.py` | Regressionstests |
