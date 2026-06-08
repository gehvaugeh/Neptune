# Security Review - Neptune

This document outlines potential security vulnerabilities identified in the Neptune codebase.

## 1. Command Injection in `server.py`
The `process_queue` method in `server.py` constructs shell commands by directly concatenating `block['cwd']` and `block['content']` into a string that is then written to the master PTY.

**Vulnerable Code:**
```python
full_cmd = f"cd {block['cwd']} 2>/dev/null; {block['content']}\necho {self.current_sentinel} $?\npwd\n"
os.write(self.master_fd, full_cmd.encode())
```

**Risk:**
A malicious client (or a compromised user account) could send a `submit` message with a specially crafted `cwd` or `content` to execute arbitrary commands outside the intended directory or command block. For example, setting `cwd` to `"; rm -rf /; #"` would result in the execution of `cd ; rm -rf /; # 2>/dev/null; ...`.

## 2. Path Traversal in `client.py`
The `export_notebook` and `import_notebook` methods in `client.py` accept a `filename` parameter and use it directly with `open()`.

**Vulnerable Code (Export):**
```python
def export_notebook(self, filename: str):
    # ...
    try:
        with open(filename, "w") as f: f.write("\n".join(md_output))
        self.notify(f"Notebook Saved: {filename}", severity="information")
    except Exception as e: self.notify(f"Save Error: {e}", severity="error")
```

**Vulnerable Code (Import):**
```python
async def import_notebook(self, filename: str):
    if not filename or not os.path.exists(filename): return
    try:
        with open(filename, "r") as f: content = f.read()
        # ...
```

**Risk:**
A user could specify a path like `../../../../etc/passwd` to overwrite or read sensitive system files (depending on the permissions of the user running the client). While the client is usually run by the local user, this is still a security risk if the client is used in a shared or restricted environment.

## 3. Insecure Unix Domain Socket Permissions
In `server.py`, the Unix Domain Socket is created without explicitly setting permissions.

**Vulnerable Code:**
```python
server = await asyncio.start_unix_server(self.handle_client, self.socket_path, limit=10 * 1024 * 1024)
```

**Risk:**
Depending on the default `umask`, the socket might be world-writable, allowing any user on the system to connect to the Neptune server and execute commands in the shared shell session.

## 4. Unauthenticated Client Connection
The server accepts connections and immediately starts processing messages from any client that connects to the Unix socket.

**Risk:**
While it's a local Unix socket, there's no additional authentication layer. If the socket permissions are loose, any local user can join the session.
