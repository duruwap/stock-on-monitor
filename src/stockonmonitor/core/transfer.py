"""포트폴리오 가져오기/내보내기 (CSV, JSON).

CSV는 엑셀에서 바로 열리도록 UTF-8 BOM으로 저장한다.
가져오기는 이 앱이 내보낸 CSV/JSON과 1.x 버전의 stocks.json을 모두 지원한다.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from stockonmonitor.core.models import Holding

CSV_COLUMNS = [
    ("market", "시장"),
    ("symbol", "종목코드"),
    ("name", "종목명"),
    ("exchange", "거래소"),
    ("avg_price", "평균단가"),
    ("quantity", "수량"),
    ("target_high", "목표가(상)"),
    ("target_low", "목표가(하)"),
    ("visible", "표시"),
]
_HEADER_ALIASES = {label: key for key, label in CSV_COLUMNS} | {key: key for key, _ in CSV_COLUMNS}


def export_holdings(holdings: list[Holding], path: Path) -> None:
    if path.suffix.lower() == ".json":
        data = {"holdings": [h.to_dict() for h in holdings]}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([label for _, label in CSV_COLUMNS])
    for h in holdings:
        d = h.to_dict()
        row = []
        for key, _ in CSV_COLUMNS:
            v = d.get(key)
            if key == "visible":
                v = "Y" if v else "N"
            elif v is None:
                v = ""
            elif isinstance(v, float) and v == int(v):
                v = int(v)
            row.append(v)
        writer.writerow(row)
    path.write_text(buf.getvalue(), encoding="utf-8-sig", newline="")


def import_holdings(path: Path) -> list[Holding]:
    text = _read_text(path)
    if path.suffix.lower() == ".json" or text.lstrip().startswith(("[", "{")):
        data = json.loads(text)
        items = data.get("holdings", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError("지원하지 않는 JSON 형식입니다.")
        raw_items = [i for i in items if isinstance(i, dict)]
    else:
        reader = csv.DictReader(io.StringIO(text))
        raw_items = []
        for row in reader:
            item = {}
            for header, value in row.items():
                key = _HEADER_ALIASES.get((header or "").strip())
                if key:
                    item[key] = (value or "").strip()
            if "visible" in item:
                item["visible"] = item["visible"].upper() not in ("N", "FALSE", "0", "")
            raw_items.append(item)

    result = []
    for raw in raw_items:
        raw.pop("id", None)  # 가져온 항목은 항상 새 id를 받는다
        h = Holding.from_dict(raw)
        if h:
            result.append(h)
    if not result and raw_items:
        raise ValueError("가져올 수 있는 종목이 없습니다.")
    return result


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("파일 인코딩을 인식할 수 없습니다 (UTF-8 또는 CP949만 지원).")
