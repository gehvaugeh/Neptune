import pytest
import time
import os
import asyncio
from unittest.mock import MagicMock
from client import ClientApp, NoteBlock, CommandBlock
from common import fuzzy_match

@pytest.mark.asyncio
async def test_performance_import_large_notebook():
    """Measure the time it takes to parse a large notebook."""
    import sys
    import os
    sys.path.append(os.path.join(os.getcwd(), "scripts"))
    from generate_stress_test import generate_markdown
    filename = "perf_test_large.md"
    num_blocks = 500
    generate_markdown(num_blocks, filename)

    class DummyApp:
        def __init__(self):
            self.user_id = "test-user"
        def query_one(self, q): return MagicMock()
        def notify(self, m, severity=None): pass
        async def send_message(self, msg): self.last_msg = msg

    app = DummyApp()

    start_time = time.perf_counter()
    await ClientApp.import_notebook(app, filename)
    end_time = time.perf_counter()

    duration = end_time - start_time
    print(f"\nImporting {num_blocks} blocks took {duration:.4f} seconds")

    os.remove(filename)
    assert duration < 2.0  # Threshold, adjust as needed

def test_performance_fuzzy_match_large_content():
    """Measure fuzzy match performance on large strings."""
    query = "perf"
    target = "This is a very long string used to test the performance of the fuzzy matching algorithm. " * 1000

    start_time = time.perf_counter()
    for _ in range(1000):
        fuzzy_match(query, target)
    end_time = time.perf_counter()

    duration = end_time - start_time
    print(f"\n1000 fuzzy matches on large string took {duration:.4f} seconds")
    assert duration < 0.5

@pytest.mark.asyncio
async def test_performance_terminal_render_latency():
    """Measure the latency of rendering terminal output in CommandBlock."""
    # Mocking ClientApp with minimal necessary attributes
    app = MagicMock(spec=ClientApp)
    app.preferred_cols = 80
    app.preferred_rows = 24
    app.input_mode = "NORMAL"

    block = CommandBlock(block_id="test", command="ls", cwd="/tmp", app_ref=app)

    # Simulate large output
    large_output = "Line data\n" * 1000

    # We need to mock some TUI parts that render_terminal touches
    block.query_one = MagicMock()
    # Mocking is_mounted property
    type(block).is_mounted = property(lambda x: True)

    start_time = time.perf_counter()
    block.append_output(large_output)
    end_time = time.perf_counter()

    duration = end_time - start_time
    print(f"\nAppending and rendering 1000 lines of output took {duration:.4f} seconds")
    assert duration < 1.0
