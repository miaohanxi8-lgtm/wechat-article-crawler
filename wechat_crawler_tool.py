# -*- coding: utf-8 -*-
"""
Reusable WeChat album crawler tool.

Run interactively:
    python wechat_crawler_tool.py

Run with arguments:
    python wechat_crawler_tool.py --url "https://mp.weixin.qq.com/mp/appmsgalbum?..." --name "专辑名" --fields all
"""

from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError

from enrich_wechat_articles import (
    DEFAULT_PRODUCTS,
    fetch_article_body,
    load_product_rules,
    match_products,
    validate_xlsx as validate_table_xlsx,
    write_xlsx as write_table_xlsx,
)
from wechat_album_export import (
    DEFAULT_PAGE_COUNT,
    HEADERS,
    AlbumJob,
    crawl_album,
    parse_album_url,
    safe_filename,
    validate_xlsx as validate_link_xlsx,
    write_xlsx as write_link_xlsx,
)


BODY_HEADER = "正文"
PRODUCT_HEADER = "产品"


@dataclass(frozen=True)
class ToolConfig:
    url: str
    name: str
    category: str
    years: set[int] | None
    fields: set[str]
    output_dir: Path
    link_output: str
    enriched_output: str
    products_path: Path
    page_count: int
    album_timeout: int
    album_sleep: float
    max_pages: int
    raw_dir: Path | None
    body_timeout: int
    body_sleep: float


def parse_fields(value: str) -> set[str]:
    tokens = {token.strip().lower() for token in re.split(r"[,，、;；/\s]+", value) if token.strip()}
    if not tokens:
        return {"list"}

    fields = {"list"}
    for token in tokens:
        if token in {"list", "links", "link", "列表", "链接"}:
            fields.add("list")
        elif token in {"body", "text", "content", "正文"}:
            fields.add("body")
        elif token in {"product", "products", "产品"}:
            fields.add("products")
        elif token in {"all", "全部"}:
            fields.update({"body", "products"})
        else:
            raise ValueError(f"Unknown field option: {token}")
    return fields


def parse_years(value: str) -> set[int] | None:
    value = value.strip()
    if not value:
        return None

    years: set[int] = set()
    for part in re.split(r"[,，、;；/\s]+", value):
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                start, end = end, start
            years.update(range(start, end + 1))
        else:
            years.add(int(part))
    return years or None


def ensure_xlsx(name: str) -> str:
    return name if name.lower().endswith(".xlsx") else f"{name}.xlsx"


def default_name_from_url(url: str) -> str:
    try:
        _biz, album_id = parse_album_url(url)
    except ValueError:
        return "微信公众号专辑"
    return f"微信专辑_{album_id[-8:]}"


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def interactive_config(args: argparse.Namespace) -> ToolConfig:
    print("微信公众号专辑爬虫小工具")
    print("需要的是公众号专辑/合集链接，通常包含 /mp/appmsgalbum、__biz、album_id。")

    url = args.url or ask("专辑链接")
    while not url:
        url = ask("专辑链接")

    default_name = args.name or default_name_from_url(url)
    name = ask("专辑名称", default_name)
    category = ask("分类", args.category or name)
    years = parse_years(ask("只保留哪些年份，留空表示全部，例如 2025,2026 或 2024-2026", args.years or ""))

    fields_help = "list=只导出链接表，body=加正文，products=加产品，all=正文+产品"
    fields = parse_fields(ask(f"需要输出什么字段？{fields_help}", args.fields))

    output_dir = Path(ask("输出目录", args.output_dir))
    products_path = Path(args.products)
    if "products" in fields:
        products_path = Path(ask("产品知识库 CSV", str(products_path)))

    return build_config(
        args=args,
        url=url,
        name=name,
        category=category,
        years=years,
        fields=fields,
        output_dir=output_dir,
        products_path=products_path,
    )


def build_config(
    *,
    args: argparse.Namespace,
    url: str,
    name: str,
    category: str,
    years: set[int] | None,
    fields: set[str],
    output_dir: Path,
    products_path: Path,
) -> ToolConfig:
    safe_name = safe_filename(name)
    link_output = ensure_xlsx(args.output or f"{safe_name}_文章链接.xlsx")

    if "body" in fields and "products" in fields:
        suffix = "含正文产品"
    elif "body" in fields:
        suffix = "含正文"
    elif "products" in fields:
        suffix = "含产品"
    else:
        suffix = ""
    enriched_output = ensure_xlsx(args.enriched_output or f"{safe_name}_{suffix}.xlsx") if suffix else ""

    return ToolConfig(
        url=url,
        name=name,
        category=category or name,
        years=years,
        fields=fields,
        output_dir=output_dir,
        link_output=link_output,
        enriched_output=enriched_output,
        products_path=products_path,
        page_count=args.page_count,
        album_timeout=args.timeout,
        album_sleep=args.sleep,
        max_pages=args.max_pages,
        raw_dir=Path(args.raw_dir) if args.raw_dir else None,
        body_timeout=args.body_timeout,
        body_sleep=args.body_sleep,
    )


def config_from_args(args: argparse.Namespace) -> ToolConfig:
    if not args.url:
        return interactive_config(args)

    name = args.name or default_name_from_url(args.url)
    fields = parse_fields(args.fields)
    return build_config(
        args=args,
        url=args.url,
        name=name,
        category=args.category or name,
        years=parse_years(args.years or ""),
        fields=fields,
        output_dir=Path(args.output_dir),
        products_path=Path(args.products),
    )


def enrich_table(
    rows: list[list[str]],
    *,
    include_body: bool,
    include_products: bool,
    products_path: Path,
    timeout: int,
    sleep_seconds: float,
) -> list[list[str]]:
    headers = list(HEADERS)
    if include_body and BODY_HEADER not in headers:
        headers.append(BODY_HEADER)
    if include_products and PRODUCT_HEADER not in headers:
        headers.append(PRODUCT_HEADER)

    title_idx = headers.index("标题")
    url_idx = headers.index("url")
    body_idx = headers.index(BODY_HEADER) if include_body else None
    product_idx = headers.index(PRODUCT_HEADER) if include_products else None

    rules = []
    if include_products:
        if not products_path.exists():
            raise FileNotFoundError(f"Product knowledge base not found: {products_path}")
        rules = load_product_rules(products_path)

    output = [headers]
    for row_num, original_row in enumerate(rows, 1):
        row = list(original_row) + [""] * (len(headers) - len(original_row))
        title = row[title_idx]
        url = row[url_idx]
        try:
            body = fetch_article_body(url, timeout)
            product = match_products(title, body, rules) if include_products else ""
            if body_idx is not None:
                row[body_idx] = body
            if product_idx is not None:
                row[product_idx] = product
            print(f"{row_num:02d}. ok body={len(body)} product={product or '-'} title={title}")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            if body_idx is not None:
                row[body_idx] = f"[抓取失败] {exc}"
            if product_idx is not None:
                row[product_idx] = ""
            print(f"{row_num:02d}. failed title={title}: {exc}")
        output.append(row)
        time.sleep(sleep_seconds)
    return output


def run(config: ToolConfig) -> None:
    parse_album_url(config.url)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    job = AlbumJob(
        name=config.name,
        url=config.url,
        category=config.category,
        output_name=config.link_output,
        years=config.years,
    )

    rows = crawl_album(
        job,
        page_count=config.page_count,
        timeout=config.album_timeout,
        sleep_seconds=config.album_sleep,
        max_pages=config.max_pages,
        raw_dir=config.raw_dir,
    )

    link_path = write_link_xlsx(config.output_dir / config.link_output, rows)
    validate_link_xlsx(link_path, len(rows))
    print(f"wrote {link_path} ({len(rows)} rows)")

    include_body = "body" in config.fields
    include_products = "products" in config.fields
    if not include_body and not include_products:
        return

    enriched = enrich_table(
        rows,
        include_body=include_body,
        include_products=include_products,
        products_path=config.products_path,
        timeout=config.body_timeout,
        sleep_seconds=config.body_sleep,
    )
    enriched_path = write_table_xlsx(config.output_dir / config.enriched_output, enriched)
    validate_table_xlsx(enriched_path, len(enriched))
    print(f"wrote {enriched_path} ({len(enriched) - 1} rows)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reusable crawler for WeChat public-account album pages.")
    parser.add_argument("--url", default="", help="WeChat album URL. If omitted, the tool asks interactively.")
    parser.add_argument("--name", default="", help="Album name used in logs and default output names.")
    parser.add_argument("--category", default="", help="Category value written to the Excel file. Defaults to name.")
    parser.add_argument("--years", default="", help="Optional years to keep, such as 2025,2026 or 2024-2026.")
    parser.add_argument("--fields", default="list", help="Output fields: list, body, products, or all.")
    parser.add_argument("--output-dir", default="exports", help="Directory for generated files.")
    parser.add_argument("--output", default="", help="Output filename for the article-link workbook.")
    parser.add_argument("--enriched-output", default="", help="Output filename for the body/product workbook.")
    parser.add_argument("--products", default=DEFAULT_PRODUCTS, help="Product knowledge-base CSV for product matching.")
    parser.add_argument("--page-count", type=int, default=DEFAULT_PAGE_COUNT, help="Page size for album JSON requests.")
    parser.add_argument("--timeout", type=int, default=20, help="Album JSON request timeout in seconds.")
    parser.add_argument("--sleep", type=float, default=0.15, help="Pause between album pagination requests.")
    parser.add_argument("--max-pages", type=int, default=50, help="Safety cap for album pagination.")
    parser.add_argument("--raw-dir", default="", help="Optional directory to save raw album JSON responses.")
    parser.add_argument("--body-timeout", type=int, default=25, help="Article body request timeout in seconds.")
    parser.add_argument("--body-sleep", type=float, default=0.4, help="Pause between article body requests.")
    return parser.parse_args()


def main() -> None:
    try:
        config = config_from_args(parse_args())
        run(config)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    main()
