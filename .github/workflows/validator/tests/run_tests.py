"""Run the complete validator test suite without third-party test tooling."""

import sys
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent


def main() -> int:
    suite = unittest.defaultTestLoader.discover(str(TEST_DIR), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
