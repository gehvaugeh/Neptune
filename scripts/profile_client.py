import cProfile
import pstats
import asyncio
import time
from unittest.mock import MagicMock
from client import ClientApp, NoteBlock, CommandBlock

async def profile_client_heavy():
    # Setup mock app
    app = MagicMock(spec=ClientApp)
    app.preferred_cols = 120
    app.preferred_rows = 24
    app.input_mode = "NORMAL"
    app.focused = None

    # Profile terminal rendering WITH RE-RENDERING
    print("\n--- Profiling Terminal Rendering (Many small updates) ---")
    block = CommandBlock(block_id="perf-test", command="cat large_file", cwd="/tmp", app_ref=app)
    block.query_one = MagicMock()
    type(block).is_mounted = property(lambda x: True)

    # Disable throttling for profiling the actual render logic
    block._render_throttle = 0

    pr = cProfile.Profile()
    pr.enable()
    for i in range(100):
        # Directly feed to simulate data arrival
        block.stream.feed(f"Line {i}: some data that triggers re-render\n")
        block.render_terminal()
    pr.disable()
    ps = pstats.Stats(pr).sort_stats('cumulative')
    ps.print_stats(30)

if __name__ == "__main__":
    asyncio.run(profile_client_heavy())
