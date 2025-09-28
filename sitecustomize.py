"""Support coverage collection in subprocesses started by tests."""

import os

if os.getenv("COVERAGE_PROCESS_START"):
    try:
        import coverage
    except ImportError:  # pragma: no cover - coverage package missing
        pass
    else:
        coverage.process_startup()
