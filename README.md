# 微信公众号专辑爬虫小工具

这个工具入口是：

```powershell
python wechat_crawler_tool.py
```

它适合爬微信公众号“专辑/合集”链接，链接通常包含：

```text
/mp/appmsgalbum
__biz
album_id
```

## 交互式使用

直接运行：

```powershell
python wechat_crawler_tool.py
```

然后按提示输入：

```text
专辑链接
专辑名称
分类
年份限制
需要输出的字段
输出目录
```

字段选项：

```text
list       只导出文章标题、链接、分类、发布时间
body       在链接表基础上抓正文
products   在链接表基础上匹配产品
all        同时抓正文和匹配产品
```

## 命令行使用

只导出文章链接表：

```powershell
python wechat_crawler_tool.py --url "公众号专辑链接" --name "专辑名" --fields list
```

导出正文：

```powershell
python wechat_crawler_tool.py --url "公众号专辑链接" --name "专辑名" --fields body
```

导出正文和产品匹配：

```powershell
python wechat_crawler_tool.py --url "公众号专辑链接" --name "专辑名" --fields all
```

只保留指定年份：

```powershell
python wechat_crawler_tool.py --url "公众号专辑链接" --name "专辑名" --years 2025,2026
```

测试新链接是否能抓：

```powershell
python wechat_crawler_tool.py --url "公众号专辑链接" --name "测试专辑" --page-count 5 --max-pages 2 --raw-dir raw_test
```

指定输出目录：

```powershell
python wechat_crawler_tool.py --url "公众号专辑链接" --name "专辑名" --fields all --output-dir exports
```

指定产品知识库：

```powershell
python wechat_crawler_tool.py --url "公众号专辑链接" --name "专辑名" --fields all --products yonyou_product_knowledge_base.csv
```

产品知识库 CSV 可参考：

```text
product_knowledge_base_template.csv
```

需要包含这些表头：

```text
产品,分类,产品别名,关键词,功能模块
```

## 复用逻辑

这个工具没有重写爬虫核心，而是复用：

```text
wechat_album_export.py       抓专辑文章列表
enrich_wechat_articles.py    抓正文和匹配产品
```

如果目标不是微信公众号专辑/合集链接，而是公众号历史消息页、搜索结果页、普通文章列表，就需要重新分析接口，不能保证只换 URL 就能用。
