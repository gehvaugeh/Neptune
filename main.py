import sys
import os
import subprocess
import signal
from branding import setup_parser, check_args

def main():
    parser = setup_parser("Neptune Multi-User Launcher")
    parser.add_argument("mode", choices=["server", "client", "all"], nargs="?", help="Mode to start: server, client, or all")
    parser.add_argument("-s", "--socket", default="/tmp/neptune.sock", help="Path to the Unix Domain Socket")
    parser.add_argument("--enable-hist-expansion", action="store_true", help="Enable Bash history expansion (e.g. using !)")

    check_args(parser)

    # We use parse_known_args to allow passing mode and socket, and then handle the rest
    args, unknown = parser.parse_known_args()

    mode = args.mode
    if not mode:
        parser.print_help()
        sys.exit(0)
    socket_path = args.socket

    if mode == "server":
        import server
        s = server.Server(socket_path=socket_path, enable_hist_expansion=args.enable_hist_expansion)
        server.asyncio.run(s.start())
    elif mode == "client":
        import client
        client.ClientApp(socket_path=socket_path).run()
    elif mode == "all":
        # Start server in background
        server_args = [sys.executable, "server.py", "-s", socket_path]
        if args.enable_hist_expansion:
            server_args.append("--enable-hist-expansion")
        server_proc = subprocess.Popen(server_args)
        try:
            # Start client
            import client
            client.ClientApp(socket_path=socket_path).run()
        finally:
            # Cleanup server when client closes
            os.kill(server_proc.pid, signal.SIGTERM)

if __name__ == "__main__":
    main()
