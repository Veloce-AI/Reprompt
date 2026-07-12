"""Ensure both packages are importable under Python 3.14, where .pth files
in the venv's site-packages are not always processed automatically (a
regression in Python 3.14.0 with uv-generated editable installs).
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_SRC = _REPO_ROOT / "apps" / "api" / "src"
_CORE_SRC = _REPO_ROOT / "packages" / "core" / "src"

for _p in (_API_SRC, _CORE_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
