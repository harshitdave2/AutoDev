"""Thin compatibility entry point.

The real CLI lives in ``autodev.py`` (single source of truth). This module
previously held a stale copy that lacked ``--mode``/``--fast``, ignored the
configured model, and always exited 0.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from autodev import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
