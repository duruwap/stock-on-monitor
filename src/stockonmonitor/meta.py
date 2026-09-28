"""배포 관련 메타데이터의 단일 출처.

빌드 스크립트(packaging/build.ps1)와 설치 프로그램(installer/StockOnMonitor.iss)도
이 파일의 값을 읽어 사용한다. 배포 사이트가 정해지면 이 파일만 수정하면 된다.
"""

from stockonmonitor import __version__

APP_ID = "StockOnMonitor"              # 폴더명·레지스트리 키·뮤텍스 이름의 기반 (변경 금지)
APP_NAME = "StockOnMonitor"            # 사용자에게 보이는 이름
APP_VERSION = __version__
APP_PUBLISHER = "StockOnMonitor"
APP_COPYRIGHT = "© 2026 StockOnMonitor"
APP_EXE_NAME = "StockOnMonitor.exe"

# Windows 알림(토스트)과 작업 표시줄 그룹화에 쓰이는 식별자. 설치 프로그램의 바로가기와 반드시 같아야 한다.
APP_USER_MODEL_ID = "StockOnMonitor.Desktop"

# 설치 프로그램이 앱 실행 여부를 감지하는 데 쓰는 이름 있는 뮤텍스.
APP_MUTEX = "StockOnMonitorAppMutex"

# Inno Setup AppId. 한 번 배포한 뒤에는 절대 바꾸지 않는다(바꾸면 업그레이드가 아닌 별도 설치로 인식됨).
INSTALLER_APP_GUID = "{8C3F6E2A-5B1D-4E7A-9F0C-2D6B8A4E1C73}"

# 배포 사이트. 비워 두면 해당 메뉴가 숨겨진다.
WEBSITE_URL = ""
SUPPORT_URL = ""

# 자동 업데이트 매니페스트(latest.json) 주소. 비워 두면 업데이트 확인 기능이 꺼진다.
# 형식은 docs/DEPLOYMENT.md 참고. 반드시 https 주소여야 한다.
UPDATE_MANIFEST_URL = ""

# 설치 프로그램이 데이터 폴더 위치를 기록하는 레지스트리 경로 (HKCU)
REGISTRY_KEY = rf"Software\{APP_ID}"
REGISTRY_DATA_DIR_VALUE = "DataDir"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
