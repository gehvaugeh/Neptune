import sys
import os
import subprocess
import signal
import argparse
import asyncio

from common import THEME_FILE

def main():
    parser = argparse.ArgumentParser(description="Gemmi-Shell Multi-User Launcher")
    parser.add_argument("mode", choices=["server", "client", "all"], help="Mode to start: server, client, or all")
    parser.add_argument("-s", "--socket", default="/tmp/gemmi_shell.sock", help="Path to the Unix Domain Socket")

    # We use parse_known_args to allow passing mode and socket, and then handle the rest
    args, unknown = parser.parse_known_args()

    mode = args.mode
    socket_path = args.socket

    if mode == "server":
        import server
        asyncio.run(server.main(socket_path))
    elif mode == "client":
        import client
        client.ClientApp(socket_path=socket_path).run()
    elif mode == "all":
        # Start server in background
        server_proc = subprocess.Popen([sys.executable, "server.py", "-s", socket_path])
        try:
            # Start client
            import client
            client.ClientApp(socket_path=socket_path).run()
        finally:
            # Cleanup server when client closes
            os.kill(server_proc.pid, signal.SIGTERM)

if __name__ == "__main__":
    main()
