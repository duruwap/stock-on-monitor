"""meta.py 값을 읽어 빌드에 필요한 정보를 출력/생성한다.

    python packaging/make_version_info.py version       # 버전 문자열 출력
    python packaging/make_version_info.py iss-defines   # Inno Setup /D 인자 출력 (한 줄에 하나)
    python packaging/make_version_info.py rc <출력경로>  # PyInstaller용 Windows 버전 리소스 생성
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stockonmonitor import meta  # noqa: E402


def version_tuple() -> tuple[int, int, int, int]:
    parts = [int(p) for p in meta.APP_VERSION.split("-")[0].split(".")]
    return tuple((parts + [0, 0, 0, 0])[:4])  # type: ignore[return-value]


def write_rc(path: Path) -> None:
    v = version_tuple()
    text = f"""# 자동 생성 파일 — 직접 수정하지 마세요 (packaging/make_version_info.py)
VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041204B0', [
      StringStruct('CompanyName', {meta.APP_PUBLISHER!r}),
      StringStruct('FileDescription', {meta.APP_NAME!r}),
      StringStruct('FileVersion', {meta.APP_VERSION!r}),
      StringStruct('InternalName', {meta.APP_ID!r}),
      StringStruct('LegalCopyright', {meta.APP_COPYRIGHT!r}),
      StringStruct('OriginalFilename', {meta.APP_EXE_NAME!r}),
      StringStruct('ProductName', {meta.APP_NAME!r}),
      StringStruct('ProductVersion', {meta.APP_VERSION!r})])]),
    VarFileInfo([VarStruct('Translation', [0x0412, 1200])])
  ]
)
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def iss_defines() -> list[str]:
    values = {
        "AppId": meta.INSTALLER_APP_GUID,
        "AppIdName": meta.APP_ID,
        "AppName": meta.APP_NAME,
        "AppVersion": meta.APP_VERSION,
        "AppPublisher": meta.APP_PUBLISHER,
        "AppCopyright": meta.APP_COPYRIGHT,
        "AppExeName": meta.APP_EXE_NAME,
        "AppMutex": meta.APP_MUTEX,
        "AppUserModelId": meta.APP_USER_MODEL_ID,
        "AppURL": meta.WEBSITE_URL,
        "SupportURL": meta.SUPPORT_URL,
        "RegistryKey": meta.REGISTRY_KEY,
        "DataDirValue": meta.REGISTRY_DATA_DIR_VALUE,
    }
    return [f"/D{k}={v}" for k, v in values.items()]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "version"
    if cmd == "version":
        print(meta.APP_VERSION)
    elif cmd == "iss-defines":
        print("\n".join(iss_defines()))
    elif cmd == "rc":
        write_rc(Path(sys.argv[2]))
    else:
        raise SystemExit(f"알 수 없는 명령: {cmd}")
