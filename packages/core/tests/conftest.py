"""Ensure refract_core is importable under Python 3.14, where .pth files
in the venv's site-packages are not always processed automatically (a
regression in Python 3.14.0 with uv-generated editable installs).
"""

import sys
from pathlib import Path

_CORE_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(_CORE_SRC))
