# Performance Review - Neptune

This document identifies performance bottlenecks and proposes improvements to enhance the speed and efficiency of the Neptune application.

## 1. Master Output Handling and Regex Operations
In `server.py`, the `handle_master_output` method appends all incoming master shell data to `self.current_block["output"]` and performs a regular expression search on the entire buffer on each new chunk of data.

**Problematic Code:**
```python
async def handle_master_output(self, data):
    self.current_block["output"] += data
    pattern = rf'{self.current_sentinel}\s+(\d+)\s*\r?\n(.*?)\r?\n'
    match = re.search(pattern, self.current_block["output"], re.DOTALL)
    # ...
```

**Problem:**
If a command produces a large amount of output (e.g., millions of lines), the string concatenation and regex searching on increasingly larger strings will become computationally expensive and potentially lead to high CPU usage or "hanging" the server loop.

**Improvement:**
Instead of searching the entire buffer, perform the regex search only on the last few hundred characters of the buffer where the sentinel is likely to appear. Alternatively, use a more efficient way to detect the sentinel string without repeated regexes on a large string.

## 2. Broadcast Function Overhead
The `broadcast` method in `server.py` sends messages to all connected clients by iterating over the `self.clients` dictionary and creating an `asyncio.task` for each client.

**Problematic Code:**
```python
async def broadcast(self, message):
    data = json.dumps(message).encode() + b"\n"
    # ...
    clients = list(self.clients.items())
    for writer, client_info in clients:
        asyncio.create_task(self.send_to_client(writer, data, client_info['id']))
```

**Problem:**
In a collaborative session with many users, broadcasting large messages (like the entire list of blocks in an `init` or `reorder` message) can generate significant network traffic and server-side overhead. Frequent broadcasts (like on every single character of output) can exacerbate this.

**Improvement:**
Implement message batching or a more efficient broadcasting mechanism. For output specifically, consider buffering characters and broadcasting in larger chunks.

## 3. Client UI Rendering and Block Reordering
In `client.py`, the `on_server_message` handler for the `reorder` message removes and recreates all block widgets if they are not already present, and uses `container.move_child()` to rearrange existing widgets.

**Problematic Code:**
```python
elif msg_type == "reorder":
    container = self.query_one("#command_history")
    # ...
    for i, b_data in enumerate(new_blocks_data):
        # ...
        if i == 0:
            if container.children and container.children[0] != block:
                container.move_child(block, before=container.children[0])
        else:
            prev_id = new_blocks_data[i-1]["id"]
            if prev_id in self.blocks:
                container.move_child(block, after=self.blocks[prev_id])
```

**Problem:**
Textual's `move_child()` operation can be relatively expensive if it triggers a full layout recalculation for every single moved widget. In a session with hundreds of blocks, reordering could cause noticeable lag in the UI.

**Improvement:**
Optimize how block widgets are updated and reordered. Instead of calling `move_child()` in a loop, consider more efficient ways to update the widget list if supported by the Textual version, or only update the parts of the UI that have changed.

## 4. Large Output Buffer in `server.py`
The server keeps the full output for all command blocks in memory (`self.blocks`).

**Problem:**
For long-running sessions with many large-output commands, the server's memory usage will grow indefinitely.

**Improvement:**
Implement a limit on the amount of output stored for each block (e.g., keep only the last 1000 lines) or persist large outputs to disk.
