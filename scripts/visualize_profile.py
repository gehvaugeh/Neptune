import asyncio
import os
import time
from unittest.mock import MagicMock
from client import ClientApp, CommandBlock, NoteBlock

async def run_visualization_scenario():
    print("Initializing Neptune Client scenario for visualization...")

    # Mocking ClientApp for a headless run
    app = ClientApp()
    app.preferred_cols = 120
    app.preferred_rows = 24
    app.query_one = MagicMock()
    app.notify = MagicMock()
    app.send_message = MagicMock(return_value=asyncio.Future())
    app.send_message.return_value.set_result(None)

    # Step 1: Create a large notebook if not present
    filename = "big_example.md"
    if not os.path.exists(filename):
        print("Generating 1000 blocks...")
        from scripts.generate_stress_test import generate_markdown
        generate_markdown(1000, filename)

    # Step 2: Import the massive notebook
    print(f"Step 2: Importing {filename}...")
    await app.import_notebook(filename)

    # Step 3: Simulate output bursts in multiple blocks
    print("Step 3: Simulating output in multiple command blocks...")
    cmd_blocks = [b for b in app.blocks.values() if isinstance(b, CommandBlock)][:10]
    for i, block in enumerate(cmd_blocks):
        block.query_one = MagicMock()
        type(block).is_mounted = property(lambda x: True)
        # Disable throttling for the profile to see raw cost
        block._render_throttle = 0

        output = f"Data stream for block {i}\n" * 50
        block.append_output(output)

    # Step 4: Simulate filtering
    print("Step 4: Simulating filtering...")
    await app._run_filter("Line 10")

    print("Scenario complete.")
    if os.path.exists(filename):
        os.remove(filename)

if __name__ == "__main__":
    asyncio.run(run_visualization_scenario())
