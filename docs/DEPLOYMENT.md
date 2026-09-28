# 배포 가이드

웹사이트에서 설치 파일을 내려받는 방식으로 배포하는 절차입니다.

## 0. 최초 1회 설정

`src/stockonmonitor/meta.py`에서 배포 정보를 채웁니다.

| 항목 | 설명 |
| --- | --- |
| `APP_PUBLISHER`, `APP_COPYRIGHT` | 설치 프로그램·파일 속성·제어판에 표시되는 게시자 |
| `WEBSITE_URL`, `SUPPORT_URL` | 설정 → 정보, 제어판 "프로그램 제거" 화면에 표시 |
| `UPDATE_MANIFEST_URL` | 자동 업데이트용 `latest.json` 주소 (**https 필수**). 비우면 업데이트 기능이 꺼짐 |

> `APP_ID`, `INSTALLER_APP_GUID`, `APP_MUTEX`, `APP_USER_MODEL_ID`는 **한 번 배포한 뒤 절대 바꾸지 마세요.**
> 바꾸면 기존 설치본이 업그레이드되지 않고 따로 설치되며, 데이터 위치·자동 실행 설정도 끊깁니다.

## 1. 버전 올리기

1. `src/stockonmonitor/__init__.py`의 `__version__` 수정 (예: `2.0.1`)
2. `CHANGELOG.md`에 변경 사항 기록

## 2. 빌드

### GitHub Actions (권장)

```bash
git tag v2.0.1 && git push origin v2.0.1
```

`build` 워크플로가 테스트 → 설치 파일 빌드 → **초안(draft) 릴리스**에 `StockOnMonitor-Setup-2.0.1.exe`와
`latest.json`을 첨부합니다. 저장소 변수 `DOWNLOAD_BASE_URL`(Settings → Variables)을 설정해 두면
`latest.json`의 다운로드 주소가 자동으로 채워집니다. 수동 실행(workflow_dispatch) 시 입력값으로도 지정할 수 있습니다.

### 로컬 (Windows)

준비물: Python 3.12, Inno Setup 6 (`winget install JRSoftware.InnoSetup`)

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 `
    -DownloadBaseUrl https://example.com/download -ReleaseNotes "버그 수정"
```

결과물은 `build\installer\`에 생성됩니다.

## 3. 코드 서명 (강력 권장)

서명하지 않은 설치 파일을 웹에서 내려받으면 Windows SmartScreen이 "Windows의 PC 보호" 경고를 띄우고,
회사 보안 솔루션이 실행을 막을 수 있습니다. 코드 서명 인증서(OV/EV)를 구매해 PC 인증서 저장소에 설치한 뒤:

```powershell
$env:SIGN_CERT_THUMBPRINT = "인증서 지문(40자리)"
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Sign -DownloadBaseUrl https://example.com/download
```

앱 실행 파일, 설치 프로그램, 제거 프로그램이 모두 서명됩니다. (Windows SDK의 signtool.exe 필요)

## 4. 웹사이트에 업로드

1. `StockOnMonitor-Setup-<버전>.exe`를 `DownloadBaseUrl` 위치에 업로드
2. 다운로드 페이지의 링크를 새 파일로 교체
3. **마지막으로** `latest.json`을 `UPDATE_MANIFEST_URL` 위치에 덮어쓰기
   (설치 파일보다 먼저 올리면 사용자가 존재하지 않는 파일을 내려받게 됩니다)

`latest.json` 형식:

```json
{
  "version": "2.0.1",
  "url": "https://example.com/download/StockOnMonitor-Setup-2.0.1.exe",
  "sha256": "설치 파일의 SHA-256 (build.ps1이 자동 계산)",
  "notes": "변경 사항 요약 (업데이트 확인 창에 표시)",
  "published": "2026-10-01"
}
```

앱은 시작 20초 후, 이후 12시간마다 이 파일을 확인합니다. 새 버전이 있으면 트레이 알림을 한 번 띄우고,
사용자가 메뉴의 **업데이트 설치**를 누르면 내려받아 SHA-256을 검증한 뒤 조용히 설치하고 다시 실행합니다.

## 설치 프로그램 동작 요약

| 상황 | 동작 |
| --- | --- |
| 기본 설치 | 관리자 권한 없이 `%LOCALAPPDATA%\Programs\StockOnMonitor`에 설치 (설치 대화상자에서 "모든 사용자" 선택 가능) |
| 데이터 위치 | 첫 설치 때 선택 (기본 `%APPDATA%\StockOnMonitor`), 폴더를 미리 생성하고 `HKCU\Software\StockOnMonitor\DataDir`에 기록 |
| 업그레이드 | 실행 중인 앱을 종료(무인 모드에서는 자동) → 이전 라이브러리 정리 → 설치 → 데이터 위치 유지 |
| 제거 | 실행 중인 앱 종료 → 파일·바로가기·자동 실행 제거 → 데이터 삭제 여부 확인 (무인 제거 시 데이터 보존) |

무인 설치(사내 일괄 배포 등):

```
StockOnMonitor-Setup-2.0.1.exe /VERYSILENT /SUPPRESSMSGBOXES /DATADIR="D:\Data\StockOnMonitor" /TASKS="autostart"
```

- `/TASKS=` 로 `desktopicon`(바탕화면 아이콘), `autostart`(자동 실행) 선택. 생략하면 둘 다 설치
- `/ALLUSERS` 모든 사용자용 설치(관리자 권한 필요), `/CURRENTUSER` 현재 사용자용
- `/LOG="경로"` 설치 로그 저장

## 포터블 실행

설치 폴더(또는 `build\dist\StockOnMonitor`)에 `portable`이라는 빈 파일을 만들면 데이터가 실행 파일 옆 `data` 폴더에 저장됩니다.

## 문제 해결

- 로그: 데이터 폴더의 `logs\app.log` (설정 → 정보 → 로그 폴더 열기). 자세한 로그는 `StockOnMonitor.exe --debug`
- 위젯이 화면 밖으로 사라짐: `StockOnMonitor.exe --reset-position`
- 설정 파일 손상: 앱이 자동으로 `backups\`의 최신 백업에서 복원하고 알림을 띄웁니다. 손상된 원본은 `*.corrupt-<시각>`으로 보존됩니다.
