# Architecture Review - Neptune

This document identifies architectural areas of Neptune that could be improved for better reusability, modularity, and maintainability.

## 1. Modularize Message Dispatching
In both `server.py` and `client.py`, incoming messages are handled via large `if/elif` chains in `handle_client` and `on_server_message`.

**Problematic Code (Client):**
```python
async def on_server_message(self, event: ServerMessage):
    msg = event.data
    msg_type = msg.get("type")
    if msg_type == "init": # ...
    elif msg_type == "user_join": # ...
    elif msg_type == "new_block": # ...
    # ... many more ...
```

**Improvement:**
Implement a registry-based dispatch system. Define a `handle_<message_type>` method or function for each message type and use a dictionary to map message types to their corresponding handlers. This makes it easier to add new message types and improves code readability and testability.

## 2. Decouple TUI from Business Logic
In `client.py`, the `ClientApp` class handles everything from TUI layout and events to network communication and state management.

**Problem:**
The networking code (`connect_to_server`, `listen_to_server`, `send_message`) and the local state management (`blocks`, `users`) are tightly coupled with the Textual-specific UI components.

**Improvement:**
Extract the networking and core business logic (session state, message handling) into a separate `NeptuneClient` class that is independent of the Textual UI. This would allow the Neptune core to be reused with different UI frontends (e.g., a web-based client, a CLI-only client, or even a different TUI library).

## 3. Split Large Source Files
`client.py` and `server.py` have grown into large files that contain both the core logic and the UI/PTY handling.

**Improvement:**
Split `client.py` and `server.py` into smaller, more focused modules:
- `client/ui.py`: Textual-specific UI components (Blocks, Modals, App).
- `client/core.py`: Networking and state management logic.
- `server/pty_manager.py`: PTY and shell process management.
- `server/session_manager.py`: Client connection and session state management.

## 4. Formalize Component Interfaces
Currently, many components communicate by directly accessing properties of other components (e.g., `self.app_ref.send_message`).

**Improvement:**
Define clear interfaces (abstract base classes or protocols) for communication between the UI, the network layer, and the server-side process manager. This would make the codebase more modular and easier to test using mocks or stubs.

## 5. Use Type Hinting More Consistently
While some type hinting is present, many functions and class methods lack it.

**Improvement:**
Consistently use type hints for all function arguments and return types. This will improve code clarity, catch potential bugs earlier, and provide better IDE support.
