# CLAUDE.md

이 저장소에서 작업할 때 따라야 할 지침. 사람 기여자에게도 동일하게 적용된다.

## 프로젝트 한 줄 요약

작업 표시줄 트레이에 상주하는 Windows용 주식 시세 위젯. **사무실에서 항상 켜 두어도 눈에 띄지 않는 것**이
제품의 핵심 가치다. Python 3.12 + PySide6(Qt 6), PyInstaller(onedir) + Inno Setup으로 배포.

## 자주 쓰는 명령

```bash
pip install -r requirements.txt -r requirements-dev.txt
python run.py                       # 소스에서 실행 (--debug, --data-dir ./data, --reset-position)
QT_QPA_PLATFORM=offscreen pytest    # 테스트 (Windows PowerShell: $env:QT_QPA_PLATFORM="offscreen")
ruff check .                        # 린트 (ruff check --fix . 로 자동 수정)
python tools/make_icons.py          # 아이콘 디자인 변경 시에만 (assets/ 재생성 후 커밋)
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # Windows에서 설치 파일 빌드
```

## 구조

```
src/stockonmonitor/
  app.py              Controller: 트레이·위젯·서비스 연결, 수명 주기, main()
  meta.py             ★ 앱 이름·버전·GUID·배포 URL의 단일 출처 (빌드/설치 프로그램도 여기서 읽음)
  paths.py            데이터 폴더 결정 (CLI > 환경변수 > portable > 레지스트리(설치 프로그램) > %APPDATA%)
  core/               Qt 의존성 없는 순수 로직 — 모델, 저장소, 평가 계산, 서식, 거래시간
  providers/          시세원 (naver, yahoo) + client.py(대체 경로·병렬 조회·검색 병합)
  services/           Qt 서비스 — 시세 폴링, 알림 판정, 업데이트, 단일 인스턴스, 전역 단축키
  platform/windows.py Win32 API (ctypes). 다른 OS에서는 전부 no-op
  ui/                 theme(디자인 토큰), widget(직접 그리는 플로팅 위젯), 대화상자들, icons
installer/            Inno Setup 스크립트
packaging/            PyInstaller spec, build.ps1, 버전 리소스 생성기
tests/                pytest (offscreen Qt), fixtures/ 에 API 응답 샘플
```

자세한 설계는 `docs/ARCHITECTURE.md`, 배포 절차는 `docs/DEPLOYMENT.md`.

## 디자인 원칙 (UI를 바꿀 때 반드시 지킬 것)

1. **무채색이 기본.** 색은 `ui/theme.py`의 토큰만 사용하고, 위젯 코드에 색상값을 직접 쓰지 않는다.
   위젯의 글자는 모두 같은 색·같은 굵기다(이름만 회색, 숫자만 굵게 같은 구분 금지).
2. **강조색은 드물게.** 대화상자의 accent는 주요 버튼(저장)·포커스·선택에만. 위젯에서 굵은 글씨+색은
   합계 수익률처럼 가장 중요한 값 하나에만. 경고색(warning)은 연결 문제 등 실제 문제가 있을 때만.
3. **등락 색은 채도를 낮춘 값**을 쓴다(쨍한 빨강/파랑 금지). `mono` 설정에서는 색 없이 ▲▼만.
4. **금액은 민감 정보.** `hide_amounts`가 켜지면 금액은 `•••`. 트레이 툴팁·알림에는 처음부터 금액을 넣지 않는다.
5. 새 기능은 기본값이 "조용한" 쪽이어야 한다(알림 끔, 소리 없음, 화면 공유 시 숨김 켬).
6. 사용자에게 보이는 문구는 한국어, 짧고 존댓말(~합니다/~하세요). 기술 용어·오류 원문은 로그로.

## 코드 규칙과 불변 조건

- **UI 스레드에서 네트워크 금지.** 모든 HTTP는 데몬 스레드에서 수행하고 Signal로 메인 스레드에 전달한다
  (`QuoteService`, `_SearchRunner`, `Updater` 패턴 참고). `ThreadPoolExecutor` 대신 `client.parallel_map`
  (데몬 스레드)을 쓴다 — 종료 시 네트워크 대기로 앱이 멈추지 않게.
- **HTTP는 `providers/http.py`만 사용.** urllib + 시스템 인증서/프록시 → 사내 SSL 검사 환경 호환. `requests` 추가 금지.
- **의존성 최소화.** 런타임 의존성은 PySide6-Essentials 하나다. pandas/yfinance 같은 대형 패키지를 추가하지 말 것
  (설치 파일 크기·시작 속도·백신 오탐에 직결).
- **Windows 전용 코드는 `platform/windows.py`에만** 두고 `IS_WINDOWS` 가드로 다른 OS에서 no-op가 되게 한다.
  테스트는 Linux CI에서도 돈다.
- **저장 형식 변경 시** `core/repository.py`의 `*_SCHEMA`를 올리고 `JsonDocument(migrations={이전버전: 함수})`를 추가한다.
  `from_dict()`는 모르는 키·잘못된 값에 관대해야 한다(사용자가 JSON을 손으로 고칠 수 있음).
- **절대 바꾸면 안 되는 값:** `meta.APP_ID`, `meta.INSTALLER_APP_GUID`, `meta.APP_MUTEX`, `meta.APP_USER_MODEL_ID`,
  레지스트리 경로. 바꾸면 기존 사용자의 업그레이드·데이터 위치·자동 실행이 깨진다.
- 시세 API는 비공식 웹 API다. 파서를 고칠 때는 `tests/fixtures/`에 실제 응답 샘플을 추가하고 테스트를 먼저 쓴다.
  파싱 실패는 `HttpError`로 올려 대체 시세원으로 넘어가게 한다(앱이 죽으면 안 됨).
- Qt enum은 전체 경로(`Qt.AlignmentFlag.AlignLeft`)로 쓴다. 위젯의 크기 변경은 `_resize_anchored()`를 거친다.
- **위젯 크기는 시세 변화로 흔들리면 안 된다.** 열 폭은 넓어지기만 하고(구성 변경 시에만 재계산), 행 수는
  데이터 유무와 관계없이 같다. `tests/test_ui.py::test_widget_size_does_not_jitter`가 이를 지킨다.
- 위젯 열(종목명·현재가·전일 대비·평단 대비)과 합계 3줄은 고정 구성이다. 표시 옵션을 늘리기보다 툴팁에 정보를 더하는 쪽을 택한다.

## 버전과 릴리스

- 버전은 `src/stockonmonitor/__init__.py`의 `__version__` 한 곳에서만 바꾼다.
- `CHANGELOG.md`에 변경 사항을 기록한다.
- `v2.0.1` 같은 태그를 push하면 GitHub Actions가 설치 파일과 `latest.json`을 만들어 초안 릴리스에 첨부한다.

## 알려진 제약

- 공휴일은 거래시간 판정에 반영하지 않는다(시세원이 알려주는 장 상태로 보완).
- 이 개발 환경(원격 샌드박스)에서는 네이버/야후 서버 접근이 차단되어 있어 실제 API 응답은 Windows 실기기에서 확인해야 한다.
