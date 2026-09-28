"""표준 라이브러리 기반 HTTP 클라이언트.

requests 대신 urllib을 쓰는 이유(사내 PC 환경 대응):
- Windows에서 ssl.create_default_context()는 Windows 인증서 저장소를 사용하므로,
  회사 보안 장비가 HTTPS를 중계(SSL 검사)해도 사내 루트 인증서가 그대로 인정된다.
- 프록시는 Windows 인터넷 설정(레지스트리)을 자동으로 따른다.
"""

from __future__ import annotations

import gzip
import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any

from stockonmonitor import meta

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/128.0 Safari/537.36 {meta.APP_ID}/{meta.APP_VERSION}"
)
DEFAULT_TIMEOUT = 6.0


class HttpError(Exception):
    """네트워크·HTTP·파싱 오류를 한 종류로 묶는다."""


_ssl_context = ssl.create_default_context()
_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler(),  # 시스템 프록시
    urllib.request.HTTPSHandler(context=_ssl_context),
)


def open_stream(url: str, timeout: float = 30.0):
    """대용량 다운로드용 스트림 (호출한 쪽에서 with 문으로 닫는다)."""
    return _opener.open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


def get_bytes(url: str, params: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT,
              headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        **(headers or {}),
    })
    try:
        with _opener.open(req, timeout=timeout) as resp:
            body = resp.read()
            encoding = (resp.headers.get("Content-Encoding") or "").lower()
            charset = resp.headers.get_content_charset() or ""
    except urllib.error.HTTPError as exc:
        raise HttpError(f"HTTP {exc.code} ({urllib.parse.urlsplit(url).netloc})") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise HttpError(f"연결 실패 ({urllib.parse.urlsplit(url).netloc}): {reason}") from exc

    if encoding == "gzip":
        body = gzip.decompress(body)
    elif encoding == "deflate":
        body = zlib.decompress(body)
    return body, charset


def get_json(url: str, params: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT,
             headers: dict[str, str] | None = None) -> Any:
    body, charset = get_bytes(url, params, timeout, headers)
    for enc in filter(None, (charset, "utf-8", "cp949")):
        try:
            return json.loads(body.decode(enc).lstrip("\ufeff"))
        except (UnicodeDecodeError, LookupError):
            continue
        except json.JSONDecodeError as exc:
            raise HttpError(f"응답 형식 오류: {exc}") from exc
    raise HttpError("응답 인코딩을 해석할 수 없음")
