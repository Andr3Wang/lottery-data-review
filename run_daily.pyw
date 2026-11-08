# -*- coding: utf-8 -*-
"""无控制台入口：供 Windows 计划任务调用，输出写入 logs/daily.log。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
(ROOT / "logs").mkdir(parents=True, exist_ok=True)
log = open(ROOT / "logs" / "daily.log", "a", encoding="utf-8", buffering=1)
sys.stdout = log
sys.stderr = log

import run_daily  # noqa: E402

raise SystemExit(run_daily.main())
