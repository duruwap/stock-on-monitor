# StockOnMonitor

작업 표시줄 오른쪽 아래에 조용히 상주하는 **주식 시세 위젯**입니다.
사무실에서 하루 종일 켜 두어도 눈에 띄지 않도록 무채색·반투명으로 설계했습니다.

- 국내(코스피·코스닥) 실시간 시세 + 미국 주식, 원화 환산 합계
- 트레이 아이콘 상주 (카카오톡처럼 창을 닫아도 계속 실행, 다시 실행하면 기존 창 표시)
- 관리자 권한 없이 설치되는 설치 프로그램, 자동 업데이트

## 주요 기능

| 분류 | 기능 |
| --- | --- |
| 위젯 | 목록 / 한 줄(종목 번갈아 표시) 배치 · 평소에는 옅게, 마우스를 올리면 선명하게 · 화면 가장자리 자석 정렬 · 위치 잠금 |
| 눈치 보기 | **금액 숨기기**(수익률만 표시) · **화면 공유·캡처 시 자동 숨김**(Teams/Zoom) · **전체 화면·발표 중 자동 숨김** · **전역 단축키**로 즉시 숨기기(기본 `Ctrl+Alt+H`) · 무채색 모드 |
| 시세 | 네이버(국내 실시간) → 야후 자동 대체 · 장 마감 시간에는 조회 빈도 자동 감소 · 절전 복귀 시 즉시 갱신 · 연결 문제는 작은 점 하나로만 표시 |
| 종목 관리 | 한글·영문·코드 통합 검색 · 평균단가/수량 표에서 바로 편집 · 수량 0 = 관심 종목 · CSV(엑셀)/JSON 가져오기·내보내기 |
| 알림 | 종목별 알림 가격(이상/이하) · 하루 등락률 ±N% · 같은 알림은 하루 한 번 |
| 안정성 | 원자적 저장 + 매일 자동 백업 + 손상 시 자동 복구 · 로그 파일 · 중복 실행 방지 |

## 사용법

1. 설치 후 첫 실행 시 **종목 관리** 창이 열립니다. 종목명이나 코드를 검색해 추가하고 평균단가·수량을 입력합니다.
2. 위젯은 드래그로 옮기고, **더블클릭**하면 종목 관리, **오른쪽 클릭**하면 메뉴가 열립니다.
3. 작업 표시줄 트레이 아이콘을 **클릭**하면 위젯을 숨기거나 다시 보입니다. (Windows 11에서는 `^` 안에 숨어 있을 수 있습니다 — 드래그해서 작업 표시줄에 꺼내 두세요.)
4. 행 위에 마우스를 올려 두면 평가손익·평균단가 등 상세 정보가 표시됩니다.

데이터(설정·종목·백업·로그)는 설치할 때 고른 폴더(기본 `%APPDATA%\StockOnMonitor`)에 저장됩니다.
PC를 옮길 때는 이 폴더를 복사하거나, 종목 관리에서 **내보내기/가져오기**를 사용하세요.

> 시세 정보는 네이버 증권·Yahoo Finance에서 가져오며 지연되거나 부정확할 수 있습니다. 투자 판단의 책임은 이용자에게 있습니다.

## 개발

```bash
python -m venv .venv && .venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python run.py --debug --data-dir ./data              # 개발용 데이터 폴더를 따로 사용
pytest                                               # 테스트 (화면 없이: QT_QPA_PLATFORM=offscreen)
ruff check .
```

설치 파일 빌드(Windows, [Inno Setup 6](https://jrsoftware.org/isdl.php) 필요):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -DownloadBaseUrl https://example.com/download
# → build\installer\StockOnMonitor-Setup-<버전>.exe, latest.json
```

- 프로젝트 구조와 코드 규칙: [CLAUDE.md](CLAUDE.md)
- 설계 설명: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 배포(웹사이트 업로드·자동 업데이트·코드 서명): [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- 변경 이력: [CHANGELOG.md](CHANGELOG.md)

## 라이선스 고지

이 프로그램은 Qt for Python(PySide6, LGPL v3)을 동적 링크로 사용합니다. 설치 폴더의 `_internal\PySide6`에 있는
Qt 라이브러리는 사용자가 호환되는 다른 버전으로 교체할 수 있습니다. 그 밖의 오픈소스 목록은 앱의 **설정 → 정보**에서 확인할 수 있습니다.
