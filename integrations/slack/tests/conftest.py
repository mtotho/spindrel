"""Make the slack integration directory importable for tests."""
import sys
from pathlib import Path

_slack_dir = str(Path(__file__).resolve().parent.parent)
if _slack_dir not in sys.path:
    sys.path.insert(0, _slack_dir)
