# -*- coding: utf-8 -*-
"""将项目根目录加入 sys.path，便于直接运行 scripts/*.py"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
