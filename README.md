# 微信公众号专辑采集与内容结构化工具

一个面向微信公众号“专辑 / 合集”页面的 Python 命令行工具。输入专辑链接后，可分页采集文章元数据，按年份筛选并去重，进一步提取正文、匹配产品标签，最后导出为可直接筛选的 Excel 文件。

> 仅使用 Python 标准库，无需安装第三方依赖。建议使用 Python 3.10 及以上版本。

## 它解决什么问题

公众号专辑里的内容适合阅读，却不方便批量检索、归档和分析。这个工具把分散的文章转成结构化数据，支持以下四种输出模式：

| 模式 | 输出内容 | 适用场景 |
| --- | --- | --- |
| `list` | 标题、链接、分类、发布时间 | 建立文章索引 |
| `body` | 文章索引 + 正文 | 内容归档与文本分析 |
| `products` | 文章索引 + 产品标签 | 按业务对象整理内容 |
| `all` | 文章索引 + 正文 + 产品标签 | 完整内容结构化 |

## 处理流程

```mermaid
flowchart LR
    A[微信公众号专辑链接] --> B[解析 biz 与 album_id]
    B --> C[游标分页抓取]
    C --> D[文章去重与年份筛选]
    D --> E[正文提取与清洗]
    E --> F[产品规则匹配]
    F --> G[生成 Excel]
```

核心设计包括：

- 通过 `begin_msgid` 与 `begin_itemidx` 持续翻页，并设置最大页数避免异常循环。
- 使用消息 ID、文章序号和 URL 组成去重键，避免分页重叠造成重复记录。
- 根据文章发布时间提前停止无关年份的抓取，减少无效请求。
- 只提取微信正文容器中的可见文本，并过滤脚本、样式等噪声。
- 产品匹配区分产品名 / 别名等强信号与关键词 / 模块等弱信号，按权重计分并限制返回数量。
- 直接生成 XLSX 文件，保留首行冻结、自动筛选和适合阅读的列宽。

## 快速开始

克隆仓库后直接运行：

```powershell
python wechat_crawler_tool.py
```

程序会依次询问专辑链接、名称、分类、年份、输出字段和目录。

也可以通过参数一次完成：

```powershell
python wechat_crawler_tool.py `
  --url "公众号专辑链接" `
  --name "专辑名" `
  --category "内容分类" `
  --years 2025,2026 `
  --fields all `
  --output-dir exports
```

有效的专辑链接通常包含：

```text
/mp/appmsgalbum
__biz
album_id
```

## 常用示例

只导出文章索引：

```powershell
python wechat_crawler_tool.py --url "公众号专辑链接" --name "专辑名" --fields list
```

同时导出正文与产品标签：

```powershell
python wechat_crawler_tool.py --url "公众号专辑链接" --name "专辑名" --fields all
```

先小批量验证新链接：

```powershell
python wechat_crawler_tool.py --url "公众号专辑链接" --name "测试专辑" --page-count 5 --max-pages 2 --raw-dir raw_test
```

## 产品匹配规则

使用 `products` 或 `all` 模式时，需要提供产品知识库 CSV：

```powershell
python wechat_crawler_tool.py --url "公众号专辑链接" --name "专辑名" --fields all --products product_knowledge_base.csv
```

表头格式如下，仓库中的 `product_knowledge_base_template.csv` 可以直接作为模板：

```text
产品,分类,产品别名,关键词,功能模块
```

产品名和别名作为强信号；关键词和功能模块作为弱信号。通用词会被降低权重，只有强信号命中或多个弱信号共同命中时才会返回产品标签。

## 文件结构

```text
wechat_crawler_tool.py              # 通用入口：交互式与命令行调用
wechat_album_export.py              # 专辑分页、去重、筛选与 XLSX 导出
enrich_wechat_articles.py           # 正文提取、产品匹配与结果补全
product_knowledge_base_template.csv # 产品规则示例
tests/test_crawler.py                # 不访问网络的核心逻辑测试
```

`wechat_album_export.py` 还保留了批量任务示例；一般使用时优先从 `wechat_crawler_tool.py` 进入。

## 测试

测试不会访问微信接口：

```powershell
python -m unittest discover -s tests -v
```

覆盖链接解析、年份与字段参数、正文清洗、产品规则评分和 XLSX 读写。

## 使用边界

- 当前适配微信公众号专辑 / 合集页，不等同于公众号历史消息页、搜索结果页或任意文章列表。
- 微信页面结构或接口策略调整后，正文提取和分页逻辑可能需要同步更新。
- 文章正文受 Excel 单元格长度限制，超长内容会保留前 32,747 个字符并标记截断。
- 产品匹配是可解释的规则评分，不是语义模型；规则质量会直接影响结果。
- 请只采集自己拥有或已获授权的公开内容，控制请求频率，并遵守平台规则与内容版权要求。

