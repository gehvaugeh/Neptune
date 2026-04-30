import cProfile
import pstats
import asyncio
from unittest.mock import MagicMock
from client import ClientApp, NoteBlock, CommandBlock

async def profile_client_heavy():
    # Setup mock app
    app = ClientApp()
    app.preferred_cols = 120
    app.preferred_rows = 24

    # Mocking necessary parts for headless profiling
    app.query_one = MagicMock()
    app.notify = MagicMock()
    app.send_message = MagicMock(return_value=asyncio.Future())
    app.send_message.return_value.set_result(None)

    # Profile terminal rendering WITH RE-RENDERING
    print("\n--- Profiling Terminal Rendering (Many small updates) ---")
    block = CommandBlock(block_id="perf-test", command="cat large_file", cwd="/tmp", app_ref=app)
    block.query_one = MagicMock()
    type(block).is_mounted = property(lambda x: True)

    pr = cProfile.Profile()
    pr.enable()
    for i in range(100):
        block.append_output(f"Line {i}: some data that triggers re-render\n")
    pr.disable()
    ps = pstats.Stats(pr).sort_stats('cumulative')
    ps.print_stats(30)

if __name__ == "__main__":
    asyncio.run(profile_client_heavy())
