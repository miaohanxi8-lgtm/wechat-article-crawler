# -*- coding: utf-8 -*-
"""
Export WeChat public-account album articles to XLSX.

This script uses only the Python standard library. It crawls album pages through
WeChat's JSON endpoint, writes one XLSX per configured album, and writes a
merged workbook.

Usage:
    python wechat_album_export.py
    python wechat_album_export.py --output-dir exports
"""

from __future__ import annotations

import argparse
import html
import json
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape


BEIJING = timezone(timedelta(hours=8))
DEFAULT_PAGE_COUNT = 20
WORKSHEET_NAME = "文章链接"
HEADERS = ["标题", "url", "分类", "发布时间"]


@dataclass(frozen=True)
class AlbumJob:
    name: str
    url: str
    category: str
    output_name: str
    years: set[int] | None = None


ALBUMS = [
    AlbumJob(
        name="数智先锋",
        url="https://mp.weixin.qq.com/mp/appmsgalbum?action=getalbum&__biz=MjM5NjA3NjYwMA==&scene=1&album_id=3996604490265886723&count=3#wechat_redirect",
        category="数智先锋",
        output_name="数智先锋_文章链接_含发布时间.xlsx",
    ),
    AlbumJob(
        name="与领先者同行",
        url="https://mp.weixin.qq.com/mp/appmsgalbum?action=getalbum&__biz=MjM5NjA3NjYwMA==&scene=1&album_id=3705091079834877958&count=3#wechat_redirect",
        category="与领先者同行",
        output_name="与领先者同行_2025-2026_文章链接.xlsx",
        years={2025, 2026},
    ),
]

MERGED_OUTPUT_NAME = "文章链接_合并_数智先锋_与领先者同行.xlsx"


def parse_album_url(url: str) -> tuple[str, str]:
    query = parse_qs(urlparse(url).query)
    biz = first(query, "__biz")
    album_id = first(query, "album_id")
    if not biz or not album_id:
        raise ValueError(f"Missing __biz or album_id in URL: {url}")
    return biz, album_id


def first(mapping: dict[str, list[str]], key: str) -> str:
    values = mapping.get(key) or []
    return values[0] if values else ""


def article_time(create_time: str | int) -> datetime:
    return datetime.fromtimestamp(int(create_time), BEIJING)


def article_to_row(article: dict, category: str) -> list[str]:
    published = article_time(article["create_time"])
    return [
        html.unescape(str(article.get("title", "")).strip()),
        html.unescape(str(article.get("url", "")).strip()),
        category,
        published.strftime("%Y-%m-%d %H:%M:%S"),
    ]


def fetch_album_page(
    *,
    biz: str,
    album_id: str,
    page_count: int,
    timeout: int,
    referer: str,
    begin_msgid: str | None = None,
    begin_itemidx: str | None = None,
) -> dict:
    params = {
        "action": "getalbum",
        "__biz": biz,
        "album_id": album_id,
        "count": str(page_count),
        "f": "json",
    }
    if begin_msgid and begin_itemidx:
        params["begin_msgid"] = begin_msgid
        params["begin_itemidx"] = begin_itemidx

    request_url = "https://mp.weixin.qq.com/mp/appmsgalbum?" + urlencode(params)
    request = Request(
        request_url,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": referer,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 "
                "Safari/537.36 MicroMessenger/8.0"
            ),
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8-sig")

    if not text.lstrip().startswith("{"):
        raise RuntimeError(f"WeChat returned non-JSON content: {text[:120]!r}")

    data = json.loads(text)
    ret = int((data.get("base_resp") or {}).get("ret", -1))
    if ret != 0:
        raise RuntimeError(f"WeChat JSON endpoint returned ret={ret}: {text[:300]}")
    return data


def normalize_articles(value: object) -> list[dict]:
    if not value:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return value
    raise TypeError(f"Unexpected article_list type: {type(value)!r}")


def crawl_album(
    job: AlbumJob,
    *,
    page_count: int,
    timeout: int,
    sleep_seconds: float,
    max_pages: int,
    raw_dir: Path | None,
) -> list[list[str]]:
    biz, album_id = parse_album_url(job.url)
    begin_msgid: str | None = None
    begin_itemidx: str | None = None
    seen: set[tuple[str, str, str]] = set()
    articles: list[dict] = []
    min_year = min(job.years) if job.years else None

    for page_num in range(1, max_pages + 1):
        data = fetch_album_page(
            biz=biz,
            album_id=album_id,
            page_count=page_count,
            timeout=timeout,
            referer=job.url,
            begin_msgid=begin_msgid,
            begin_itemidx=begin_itemidx,
        )
        if raw_dir:
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{safe_filename(job.name)}_page_{page_num:02d}.json"
            raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        payload = data.get("getalbum_resp") or {}
        page_articles = normalize_articles(payload.get("article_list"))
        if not page_articles:
            break

        new_count = 0
        for article in page_articles:
            key = (
                str(article.get("msgid", "")),
                str(article.get("itemidx", "")),
                str(article.get("url", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            articles.append(article)
            new_count += 1

        newest = article_time(page_articles[0]["create_time"])
        oldest = article_time(page_articles[-1]["create_time"])
        print(
            f"{job.name}: page {page_num}, fetched {len(page_articles)}, "
            f"new {new_count}, {newest:%Y-%m-%d} -> {oldest:%Y-%m-%d}"
        )

        if min_year and oldest.year < min_year:
            break
        if str(payload.get("continue_flag", "0")) != "1":
            break

        begin_msgid = str(page_articles[-1].get("msgid", ""))
        begin_itemidx = str(page_articles[-1].get("itemidx", ""))
        if not begin_msgid or not begin_itemidx:
            break
        time.sleep(sleep_seconds)
    else:
        raise RuntimeError(f"Stopped after max_pages={max_pages}; pagination may be looping")

    rows = []
    for article in articles:
        published = article_time(article["create_time"])
        if job.years and published.year not in job.years:
            continue
        rows.append(article_to_row(article, job.category))
    return rows


def safe_filename(value: str) -> str:
    bad_chars = '<>:"/\\|?*'
    return "".join("_" if char in bad_chars else char for char in value)


def xml_text(value: object) -> str:
    text = str(value)
    cleaned = "".join(char if char in "\t\n\r" or ord(char) >= 32 else " " for char in text)
    return escape(cleaned)


def cell_ref(col_idx: int, row_idx: int) -> str:
    letters = ""
    n = col_idx
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row_idx}"


def cell_xml(value: object, col_idx: int, row_idx: int) -> str:
    ref = cell_ref(col_idx, row_idx)
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{xml_text(value)}</t></is></c>'


def worksheet_xml(rows: list[list[str]]) -> str:
    all_rows = [HEADERS, *rows]
    row_xml = []
    for row_idx, row in enumerate(all_rows, 1):
        cells = "".join(cell_xml(value, col_idx, row_idx) for col_idx, value in enumerate(row, 1))
        row_xml.append(f'<row r="{row_idx}">{cells}</row>')

    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  <cols>
    <col min="1" max="1" width="70" customWidth="1"/>
    <col min="2" max="2" width="120" customWidth="1"/>
    <col min="3" max="3" width="18" customWidth="1"/>
    <col min="4" max="4" width="22" customWidth="1"/>
  </cols>
  <sheetData>{''.join(row_xml)}</sheetData>
  <autoFilter ref="A1:D{len(all_rows)}"/>
</worksheet>'''


def write_xlsx(path: Path, rows: list[list[str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.stem + ".tmp.xlsx")

    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''
    workbook = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="{escape(WORKSHEET_NAME)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''
    workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''
    core = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:creator>Codex</dc:creator><cp:lastModifiedBy>Codex</cp:lastModifiedBy>
</cp:coreProperties>'''
    app = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Codex</Application>
</Properties>'''

    with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as workbook_zip:
        workbook_zip.writestr("[Content_Types].xml", content_types)
        workbook_zip.writestr("_rels/.rels", rels)
        workbook_zip.writestr("xl/workbook.xml", workbook)
        workbook_zip.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        workbook_zip.writestr("xl/worksheets/sheet1.xml", worksheet_xml(rows))
        workbook_zip.writestr("docProps/core.xml", core)
        workbook_zip.writestr("docProps/app.xml", app)

    try:
        temp_path.replace(path)
        return path
    except PermissionError:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback = path.with_name(f"{path.stem}_{timestamp}{path.suffix}")
        temp_path.replace(fallback)
        return fallback


def validate_xlsx(path: Path, expected_data_rows: int) -> None:
    with zipfile.ZipFile(path) as workbook_zip:
        sheet = workbook_zip.read("xl/worksheets/sheet1.xml").decode("utf-8")
    actual_rows = sheet.count("<row ")
    expected_rows = expected_data_rows + 1
    if actual_rows != expected_rows:
        raise RuntimeError(f"{path.name}: expected {expected_rows} rows, got {actual_rows}")


def sort_rows_desc(rows: Iterable[list[str]]) -> list[list[str]]:
    return sorted(rows, key=lambda row: row[3], reverse=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export configured WeChat album articles to XLSX.")
    parser.add_argument("--output-dir", default=".", help="Directory for generated XLSX files.")
    parser.add_argument("--page-count", type=int, default=DEFAULT_PAGE_COUNT, help="Page size for WeChat JSON requests.")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP request timeout in seconds.")
    parser.add_argument("--sleep", type=float, default=0.15, help="Pause between paginated requests.")
    parser.add_argument("--max-pages", type=int, default=50, help="Safety cap for pagination.")
    parser.add_argument("--raw-dir", default="", help="Optional directory to save raw JSON responses.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    raw_dir = Path(args.raw_dir) if args.raw_dir else None

    all_rows: list[list[str]] = []
    for job in ALBUMS:
        rows = crawl_album(
            job,
            page_count=args.page_count,
            timeout=args.timeout,
            sleep_seconds=args.sleep,
            max_pages=args.max_pages,
            raw_dir=raw_dir,
        )
        output_path = write_xlsx(output_dir / job.output_name, rows)
        validate_xlsx(output_path, len(rows))
        all_rows.extend(rows)
        years = sorted({row[3][:4] for row in rows})
        print(f"wrote {output_path} ({len(rows)} rows, years: {', '.join(years)})")

    merged_rows = sort_rows_desc(all_rows)
    merged_path = write_xlsx(output_dir / MERGED_OUTPUT_NAME, merged_rows)
    validate_xlsx(merged_path, len(merged_rows))
    print(f"wrote {merged_path} ({len(merged_rows)} rows)")


if __name__ == "__main__":
    main()
