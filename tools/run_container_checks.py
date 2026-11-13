#!/usr/bin/env python3
"""CI entry point: skipped integration tests must never count as success."""
import os
from pathlib import Path
import unittest

if not os.environ.get('LOCAL_AUDIO_TEST_IMAGE'):
    raise SystemExit('LOCAL_AUDIO_TEST_IMAGE is required; container tests may not be skipped')
root = Path(__file__).resolve().parents[1]
suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern='test_container.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful() or result.skipped or result.testsRun < 6:
    raise SystemExit(1)
