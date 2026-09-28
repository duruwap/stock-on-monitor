<#
.SYNOPSIS
  StockOnMonitor 설치 파일(Setup.exe)을 빌드한다.

.DESCRIPTION
  1) 빌드용 가상환경 준비  2) 테스트  3) PyInstaller로 앱 번들 생성
  4) (선택) 코드 서명  5) Inno Setup으로 설치 파일 생성  6) 자동 업데이트용 latest.json 생성

  결과물: build\installer\StockOnMonitor-Setup-<버전>.exe, build\installer\latest.json

.PARAMETER DownloadBaseUrl
  설치 파일을 올릴 웹 주소(폴더). latest.json 의 url 값에 사용된다.
  예: https://example.com/download

.PARAMETER Sign
  코드 서명. 환경 변수 SIGN_CERT_THUMBPRINT(인증서 지문)가 필요하다.
  (선택) SIGN_TIMESTAMP_URL — 기본값 http://timestamp.digicert.com

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -DownloadBaseUrl https://example.com/download -Sign
#>
[CmdletBinding()]
param(
    [string]$DownloadBaseUrl = "",
    [string]$ReleaseNotes = "",
    [switch]$Sign,
    [switch]$SkipTests,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$Build = Join-Path $Root "build"
$Venv = Join-Path $Root ".venv-build"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "실패 ($LASTEXITCODE): $Exe $($Arguments -join ' ')" }
}

# ── 1. Python / 가상환경 ─────────────────────────────────────
Step "빌드용 가상환경 준비"
if (-not $Python) {
    if (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py"; $PyArgs = @("-3.12") }
    else { $Python = "python"; $PyArgs = @() }
} else { $PyArgs = @() }
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    Invoke-Checked $Python ($PyArgs + @("-m", "venv", $Venv))
}
$Py = Join-Path $Venv "Scripts\python.exe"
Invoke-Checked $Py @("-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip")
Invoke-Checked $Py @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "requirements.txt", "-r", "requirements-dev.txt")

$Version = (& $Py packaging\make_version_info.py version).Trim()
Write-Host "버전: $Version"

# ── 2. 테스트 ────────────────────────────────────────────────
if (-not $SkipTests) {
    Step "테스트"
    $env:QT_QPA_PLATFORM = "offscreen"
    Invoke-Checked $Py @("-m", "pytest", "-q")
    Remove-Item Env:\QT_QPA_PLATFORM
}

# ── 3. PyInstaller ───────────────────────────────────────────
Step "앱 번들 생성 (PyInstaller)"
foreach ($dir in @("dist", "work", "installer")) {
    $p = Join-Path $Build $dir
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}
Invoke-Checked $Py @("packaging\make_version_info.py", "rc", (Join-Path $Build "version_info.txt"))
Invoke-Checked $Py @("-m", "PyInstaller", "--noconfirm", "--clean",
    "--distpath", (Join-Path $Build "dist"), "--workpath", (Join-Path $Build "work"),
    "packaging\StockOnMonitor.spec")
$AppExe = Join-Path $Build "dist\StockOnMonitor\StockOnMonitor.exe"
if (-not (Test-Path $AppExe)) { throw "번들 생성 실패: $AppExe 없음" }

# ── 4. 코드 서명 (선택) ──────────────────────────────────────
$SignTool = $null
if ($Sign) {
    Step "코드 서명"
    if (-not $env:SIGN_CERT_THUMBPRINT) { throw "SIGN_CERT_THUMBPRINT 환경 변수가 필요합니다." }
    $SignTool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
    if (-not $SignTool) { throw "signtool.exe 를 찾을 수 없습니다 (Windows SDK 설치 필요)." }
    $Ts = if ($env:SIGN_TIMESTAMP_URL) { $env:SIGN_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }
    $SignArgs = @("sign", "/fd", "sha256", "/tr", $Ts, "/td", "sha256", "/sha1", $env:SIGN_CERT_THUMBPRINT)
    Invoke-Checked $SignTool ($SignArgs + @($AppExe))
}

# ── 5. Inno Setup ────────────────────────────────────────────
Step "설치 파일 생성 (Inno Setup)"
$Iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup 6 이 필요합니다: https://jrsoftware.org/isdl.php (또는 winget install JRSoftware.InnoSetup)" }

$IsccArgs = @(& $Py packaging\make_version_info.py iss-defines) +
    @("/DSourceDir=$Build\dist\StockOnMonitor", "/DOutputDir=$Build\installer", "/Qp")
if ($SignTool) {
    $IsccArgs += "/Ssigntool=`"$SignTool`" sign /fd sha256 /tr $Ts /td sha256 /sha1 $($env:SIGN_CERT_THUMBPRINT) `$f"
    $IsccArgs += "/DSignTool=signtool"
}
Invoke-Checked $Iscc ($IsccArgs + @("installer\StockOnMonitor.iss"))

$Setup = Join-Path $Build "installer\StockOnMonitor-Setup-$Version.exe"
if (-not (Test-Path $Setup)) { throw "설치 파일 생성 실패" }

# ── 6. 업데이트 매니페스트 ───────────────────────────────────
Step "업데이트 매니페스트(latest.json) 생성"
$Hash = (Get-FileHash $Setup -Algorithm SHA256).Hash.ToLower()
$FileName = Split-Path $Setup -Leaf
$Url = if ($DownloadBaseUrl) { "$($DownloadBaseUrl.TrimEnd('/'))/$FileName" } else { "https://CHANGE-ME/$FileName" }
$Manifest = [ordered]@{
    version   = $Version
    url       = $Url
    sha256    = $Hash
    notes     = $ReleaseNotes
    published = (Get-Date -Format "yyyy-MM-dd")
}
# BOM 없는 UTF-8로 저장 (Windows PowerShell 5.1의 Set-Content -Encoding UTF8 은 BOM을 붙인다)
[IO.File]::WriteAllText((Join-Path $Build "installer\latest.json"), ($Manifest | ConvertTo-Json),
    (New-Object Text.UTF8Encoding $false))

$SizeMb = [math]::Round((Get-Item $Setup).Length / 1MB, 1)
Write-Host "`n완료" -ForegroundColor Green
Write-Host "  설치 파일 : $Setup ($SizeMb MB)"
Write-Host "  SHA-256   : $Hash"
Write-Host "  매니페스트: $(Join-Path $Build 'installer\latest.json')"
if (-not $DownloadBaseUrl) { Write-Host "  ※ -DownloadBaseUrl 을 지정하지 않아 latest.json 의 url 을 직접 수정해야 합니다." -ForegroundColor Yellow }
