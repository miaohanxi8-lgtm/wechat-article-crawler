import tempfile
import unittest
from pathlib import Path

from enrich_wechat_articles import (
    ProductRule,
    WeChatContentParser,
    match_products,
    read_xlsx,
    write_xlsx,
)
from wechat_album_export import normalize_articles, parse_album_url, safe_filename
from wechat_crawler_tool import default_name_from_url, ensure_xlsx, parse_fields, parse_years


ALBUM_URL = (
    "https://mp.weixin.qq.com/mp/appmsgalbum?"
    "action=getalbum&__biz=example_biz&album_id=1234567890#wechat_redirect"
)


class AlbumHelpersTest(unittest.TestCase):
    def test_parse_album_url(self):
        self.assertEqual(parse_album_url(ALBUM_URL), ("example_biz", "1234567890"))

    def test_parse_album_url_rejects_article_url(self):
        with self.assertRaises(ValueError):
            parse_album_url("https://mp.weixin.qq.com/s/example")

    def test_normalize_articles(self):
        article = {"title": "示例"}
        self.assertEqual(normalize_articles(article), [article])
        self.assertEqual(normalize_articles([article]), [article])
        self.assertEqual(normalize_articles(None), [])

    def test_safe_filename(self):
        self.assertEqual(safe_filename('产品/案例:"合集"'), "产品_案例__合集_")


class CliParsingTest(unittest.TestCase):
    def test_parse_fields(self):
        self.assertEqual(parse_fields("all"), {"list", "body", "products"})
        self.assertEqual(parse_fields("正文,产品"), {"list", "body", "products"})
        with self.assertRaises(ValueError):
            parse_fields("unknown")

    def test_parse_years(self):
        self.assertEqual(parse_years("2024-2026, 2028"), {2024, 2025, 2026, 2028})
        self.assertEqual(parse_years("2026-2024"), {2024, 2025, 2026})
        self.assertIsNone(parse_years(""))

    def test_output_names(self):
        self.assertEqual(ensure_xlsx("结果"), "结果.xlsx")
        self.assertEqual(ensure_xlsx("结果.XLSX"), "结果.XLSX")
        self.assertEqual(default_name_from_url(ALBUM_URL), "微信专辑_34567890")


class ContentAndMatchingTest(unittest.TestCase):
    def test_extracts_visible_article_text(self):
        parser = WeChatContentParser()
        parser.feed(
            '<div id="js_content"><p>第一段<br>第二行</p>'
            '<script>ignore()</script><img alt="流程图"></div>'
        )
        parser.close()
        self.assertEqual(parser.text(), "第一段\n第二行\n流程图")

    def test_product_matching_prefers_strong_signal(self):
        rules = [
            ProductRule("产品A", "分类", ["产品A", "别名A"], ["财务", "报表"]),
            ProductRule("产品B", "分类", ["产品B"], ["供应链", "采购"]),
        ]
        self.assertEqual(match_products("别名A发布", "财务报表升级", rules), "产品A")

    def test_generic_weak_signal_alone_is_not_enough(self):
        rules = [ProductRule("产品A", "分类", ["产品A"], ["AI", "数据"])]
        self.assertEqual(match_products("AI 数据观察", "AI 与数据", rules), "")

    def test_xlsx_round_trip(self):
        rows = [
            ["标题", "url", "分类", "发布时间", "正文", "产品"],
            ["示例", "https://example.com", "案例", "2026-01-01", "正文", "产品A"],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.xlsx"
            write_xlsx(path, rows)
            self.assertEqual(read_xlsx(path), rows)


if __name__ == "__main__":
    unittest.main()

