"""解析 Makefile 中 `目标: ## 说明` 形式的注释并打印帮助。"""

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

makefile = Path(__file__).resolve().parent.parent / "Makefile"
for target, desc in re.findall(r"^([\w-]+):.*?## (.*)$", makefile.read_text(encoding="utf-8"), re.M):
    print(f"  make {target:<16}{desc}")
