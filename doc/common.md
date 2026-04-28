# Autocomplete & Shared Utilities

Neptune features a modular autocomplete system and shared logic for consistency between client and server.

## Autocomplete System (`autocomplete.py`)

The autocomplete system uses a provider-based architecture. Every input mode can have its own `AutocompleteProvider`.

### Providers
- **BashAutocompleteProvider:**
  - **Path Completion:** Scans the local filesystem (relative to the server's CWD) and offers fuzzy-matched files and directories.
  - **History:** Offers suggestions from the command history.
  - **Workflows:** Suggests predefined commands from `termux_workflows.json`.
- **CmdAutocompleteProvider:**
  - Provides completion for internal commands like `:export`, `:import`, and `:clear`.
  - Includes descriptions for each command that are displayed in the TUI palette.
- **MarkdownAutocompleteProvider:**
  - Offers a menu of common Markdown syntax (headers, bold, links, code blocks).

### Interaction
- The palette UI (`#palette`) is dynamically populated as the user types.
- Users can navigate suggestions using `Up/Down` and select them with `Tab` or `Enter`.

## Shared Utilities (`common.py`)

- **HistoryManager:** Handles loading and saving the command history to `history.txt`.
- **Fuzzy Matching:** Implements a simple fuzzy search used by the autocomplete providers and block filtering.
- **Workflow Loader:** Reads `termux_workflows.json` to provide templates for common tasks.
- **Branding:** (`branding.py`) Centralizes the Neptune ASCII art and CLI help formatting.
