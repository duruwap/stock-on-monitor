"""개발용 실행 스크립트이자 PyInstaller 진입점.

    python run.py            # 소스에서 바로 실행
    python run.py --debug    # 자세한 로그
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from stockonmonitor.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
