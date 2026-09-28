# 설계 개요

## 실행 흐름

```
run.py → app.main()
  ├─ QApplication 생성 (트레이 상주: 마지막 창을 닫아도 종료하지 않음)
  ├─ SingleInstance: 이미 실행 중이면 "show" 메시지를 보내고 종료
  ├─ resolve_paths → 로그 설정 → 전역 예외 처리 → 설치 프로그램용 뮤텍스 생성
  ├─ Repository: settings.json / portfolio.json / state.json 로드 (손상 시 백업에서 복원)
  └─ Controller
       ├─ FloatingWidget   바탕화면 위젯 (직접 그리기)
       ├─ QSystemTrayIcon  트레이 아이콘 + 공용 메뉴
       ├─ QuoteService     주기적 시세 조회 (백그라운드 스레드) ──► snapshot_ready
       ├─ GlobalHotkey     전역 단축키 (Win32 RegisterHotKey)
       ├─ Updater          latest.json 확인·다운로드·무인 설치
       └─ 전체 화면 감지 타이머 (SHQueryUserNotificationState)
```

`snapshot_ready` → `Controller._on_snapshot` → 평가 계산(`core/valuation`) → 위젯·트레이 툴팁 갱신 → 알림 판정(`services/alerts`).

## 데이터

| 파일 | 내용 | 백업 |
| --- | --- | --- |
| `settings.json` | 사용자 설정 (`Settings`) | 매일 14개 보관 |
| `portfolio.json` | 보유/관심 종목 (`Holding` 목록) | 매일 30개 보관 |
| `state.json` | 위젯 위치, 표시 여부, 환율 캐시, 알림 기록 등 앱이 스스로 기억하는 값 | 없음 |

모든 파일은 `schema_version`을 가지며, `JsonDocument`가 원자적 쓰기(임시 파일 → fsync → 교체)와
마이그레이션·손상 복구를 담당합니다. 사용자 설정과 앱 상태를 분리한 이유는, 위젯을 드래그할 때마다
설정 파일과 그 백업이 바뀌지 않게 하기 위해서입니다.

## 시세 조회

| 대상 | 1차 | 대체 |
| --- | --- | --- |
| 국내 | 네이버 polling API (여러 종목 한 번에, 실시간) | 야후 chart API (`.KS` → `.KQ`) |
| 해외 | 야후 chart API | 네이버 해외 polling (`AAPL.O` 등) |
| 환율 | 야후 `KRW=X` | 직전 값(state.json) |
| 검색 | 네이버 자동완성(국내·해외) + 야후 검색(영문 입력 시) 병합 | 6자리 코드는 직접 조회 |

- 조회 간격: 설정값(기본 10초). 모든 관련 시장이 장외 시간이면 5분. 연속 실패 시 지수적으로 늘려 최대 5분.
- 일부 종목만 실패하면 직전 시세를 유지해 화면이 비지 않게 합니다. 전부 실패하면 위젯 오른쪽 위에 작은 점, 트레이 아이콘에도 점이 표시됩니다.
- HTTP는 urllib만 사용합니다. Windows에서는 시스템 인증서 저장소와 프록시 설정을 그대로 쓰므로 회사망(SSL 검사)에서도 동작합니다.

## 위젯 렌더링

라벨 위젯을 쓰지 않고 `paintEvent`에서 직접 그립니다. 행마다 `Cell` 목록을 만들고, 열별 최대 폭을 계산해
숫자를 오른쪽 정렬합니다. 합계 행은 각 열의 의미(가격 열=총 평가금액, 등락 열=오늘 변동, 손익 열=총 손익)에 맞춰 채웁니다.
크기가 바뀔 때 화면 오른쪽/아래에 붙어 있으면 그 모서리를 기준으로 커져 화면 밖으로 밀려나지 않습니다.

## Windows 통합 (`platform/windows.py`)

| 기능 | API |
| --- | --- |
| 설치 프로그램의 실행 감지 | `CreateMutexW` (Inno Setup `CheckForMutexes`) |
| 토스트 알림에 앱 이름 표시 | `SetCurrentProcessExplicitAppUserModelID` (바로가기의 AppUserModelID와 동일) |
| 화면 공유·캡처 제외 | `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` |
| 전체 화면·발표 감지 | `SHQueryUserNotificationState` |
| 전역 단축키 | `RegisterHotKey` + `QAbstractNativeEventFilter` (전용 숨은 창에 등록) |
| 자동 실행 | `HKCU\...\Run` 레지스트리 (설치 프로그램과 같은 값 이름) |
