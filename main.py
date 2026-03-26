import sys
import os
import subprocess
import signal

def main():
    if len(sys.argv) < 2:
        print("Gemmi-Shell Multi-User Launcher")
        print("Usage:")
        print("  python3 main.py server   - Start the server only")
        print("  python3 main.py client   - Start the client only")
        print("  python3 main.py all      - Start both server (in background) and client")
        return

    mode = sys.argv[1].lower()

    if mode == "server":
        import server
        server.asyncio.run(server.main())
    elif mode == "client":
        import client
        client.ClientApp().run()
    elif mode == "all":
        # Start server in background
        server_proc = subprocess.Popen([sys.executable, "server.py"])
        try:
            # Start client
            import client
            client.ClientApp().run()
        finally:
            # Cleanup server when client closes
            os.kill(server_proc.pid, signal.SIGTERM)
    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()
