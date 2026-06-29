# Amazon 2023 Base 数据集条目结构说明

## 1. 文档目的

本文整理当前仓库中 `base` 数据集每条记录包含的字段、字段含义、数据粒度、规模和后续使用注意事项。这里的 `base` 数据集特指本地标准化后的 Amazon Reviews 2023 基础层：

```text
data/processed/amazon_2023_base/
├── Electronics/
│   ├── reviews.base.jsonl
│   └── metadata.base.jsonl
├── Office_Products/
│   ├── reviews.base.jsonl
│   └── metadata.base.jsonl
├── manifest.json
└── stats.json
```

它由 `scripts/data/download_and_clean_amazon.py` 从 HuggingFace 数据集 `McAuley-Lab/Amazon-Reviews-2023` 流式读取并标准化生成，当前 schema 版本为 `1.1`。

---

## 2. 数据集入口与整体口径

### 2.1 来源与生成配置

| 项目 | 当前值 |
| --- | --- |
| 原始数据集 | `McAuley-Lab/Amazon-Reviews-2023` |
| 本地目录 | `data/processed/amazon_2023_base` |
| Schema version | `1.1` |
| 生成时间 | `2026-04-17T09:19:54.678911+00:00` |
| 当前类目 | `Electronics`, `Office_Products` |
| Review 文件名 | `reviews.base.jsonl` |
| Metadata 文件名 | `metadata.base.jsonl` |
| Metadata 保留范围 | `observed-items`，即只保留 review 中出现过的 `parent_asin` |

生成脚本中的核心标准化逻辑：

- review 原始路径：`raw/review_categories/{category}.jsonl`
- metadata 原始路径：`raw/meta_categories/meta_{category}.jsonl`
- review 输出：每条用户评论 / 交互一行
- metadata 输出：每个 `parent_asin` 商品一行
- 缺少 `user_id` 或 `parent_asin` 的 review 会被过滤
- 缺少 `parent_asin` 的 metadata 会被过滤
- metadata 默认只保留已在 review 表中出现过的商品

### 2.2 核心粒度约定

| 概念 | 字段 | 说明 |
| --- | --- | --- |
| 用户主键 | `user_id` | 用于构建用户历史、序列和行为样本 |
| 推荐 item 主键 | `parent_asin` | 当前最适合的推荐建模粒度，也是 review 与 metadata 的 join key |
| 变体级商品 ID | `asin` | 只存在于 review 表中，可用于后续细粒度分析，但当前不建议作为主 item 粒度 |
| 类目 | `category` | 当前为 `Electronics` 或 `Office_Products` |

当前推荐建模应优先以 `parent_asin` 为 item 粒度，因为 base 层已经围绕它完成 review 与 metadata 对齐。

---

## 3. 数据规模

### 3.1 类目规模

| Category | Reviews | Metadata | Distinct Users | Distinct `parent_asin` |
| --- | ---: | ---: | ---: | ---: |
| Electronics | 43,886,944 | 1,609,860 | 18,286,191 | 1,609,860 |
| Office_Products | 12,845,712 | 710,403 | 7,613,158 | 710,403 |
| **Total** | **56,732,656** | **2,320,263** | - | - |

补充说明：

- `metadata` 行数与各类目的 distinct `parent_asin` 数一致，说明当前 base 层在 `parent_asin` 粒度上是一物一行。
- `reviews` 与 `metadata` 在 `parent_asin` 上可直接 join。
- 这是全量级基础数据，不适合一次性全部读入内存。

### 3.2 文件体量

本地抽样验证时观察到的大致文件大小如下。这里使用 `Path.stat().st_size / 1024^3` 计算，因此单位更准确地说是 GiB；括号中补充历史体检文档按十进制口径记录的近似 GB。

| File | Approx Size |
| --- | ---: |
| `Electronics/reviews.base.jsonl` | 约 23.10 GiB（约 24.80 GB） |
| `Electronics/metadata.base.jsonl` | 约 2.82 GiB（约 3.03 GB） |
| `Office_Products/reviews.base.jsonl` | 约 6.00 GiB（约 6.44 GB） |
| `Office_Products/metadata.base.jsonl` | 约 1.17 GiB（约 1.25 GB） |

处理建议：

- 优先流式读取 JSONL。
- 避免 `pandas.read_json(..., lines=True)` 直接全量读入。
- 需要反复使用时，可先转成分区 parquet 或中间 canonical 表。
- 本机处理需遵守项目资源限制，默认按 12GB 可承受、14GB 上限估算。

---

## 4. `reviews.base.jsonl` 条目结构

### 4.1 一行代表什么

`reviews.base.jsonl` 中每一行是一条标准化后的用户评论 / 用户-商品交互记录。它同时包含：

- 用户 ID
- 商品 ID
- 评分
- 评论标题和正文
- 时间戳
- 是否 verified purchase
- helpful vote 数

从推荐系统角度看，它是构建用户行为、正负反馈、时间序列样本和召回 / 排序训练样本的基础表。

### 4.2 字段清单

下表中的“是否关键”指对推荐建模是否关键，不等同于生成脚本的强制过滤条件；脚本层面当前只因缺少 `user_id` 或 `parent_asin` 过滤 review。

| 字段 | 类型 | 是否关键 | 含义 | 生成 / 清洗规则 | 推荐用途 |
| --- | --- | --- | --- | --- | --- |
| `dataset` | string | 否 | 原始数据集名，当前固定为 `McAuley-Lab/Amazon-Reviews-2023` | 由脚本写入固定值 | 数据血缘、跨数据源区分 |
| `category` | string | 是 | 商品所属 Amazon 类目 | 来自生成时的 category 参数 | 分类建模、分类评估、路由 |
| `user_id` | string | 是 | 用户主键 | 缺失则整条 review 被过滤 | 用户历史、序列建模、用户画像 |
| `parent_asin` | string | 是 | 父商品 ID，当前主推荐 item 粒度 | 缺失则整条 review 被过滤 | 召回、排序、join metadata、评估 target |
| `asin` | string 或 null | 中 | 变体级商品 ID | 原样保留 `record.get("asin")` | 细粒度商品分析、变体关系分析 |
| `rating` | number 或 null | 是 | 用户评分，常见为 1.0 到 5.0；历史体检中存在极少量 0.0 异常值 | 原样保留 `record.get("rating")` | 显式反馈、正负样本、偏好强度 |
| `title` | string 或 null | 中 | 评论标题 | 原样保留 `record.get("title")` | 文本特征、解释、RAG 语料补充 |
| `text` | string | 中 | 评论正文 | 缺失时转为空字符串，并执行 `strip()` | 文本召回、情绪 / 偏好理解、解释证据 |
| `text_len` | int | 否 | 清洗后 `text` 的字符长度 | `len(text)` | 文本质量过滤、长度分桶、特征分析 |
| `timestamp` | int 或 null | 是 | 评论时间戳，当前样本中为 epoch milliseconds | 原样保留 `record.get("timestamp")` | 时间切分、序列排序、近期行为窗口 |
| `verified_purchase` | bool | 中 | 是否为 verified purchase | `bool(record.get("verified_purchase", False))` | 高质量交互过滤、样本加权 |
| `helpful_vote` | int 或 null | 低到中 | 评论 helpful vote 数 | 缺失时默认 0 | 内容质量权重、解释证据筛选 |

### 4.3 Review 样例

来自 `Electronics/reviews.base.jsonl` 的首行抽样，长文本已截断：

```json
{
  "dataset": "McAuley-Lab/Amazon-Reviews-2023",
  "category": "Electronics",
  "user_id": "AFKZENTNBQ7A7V7UXW5JJI6UGRYQ",
  "parent_asin": "B083NRGZMM",
  "asin": "B083NRGZMM",
  "rating": 3.0,
  "title": "Smells like gasoline! Going back!",
  "text": "First & most offensive: they reek of gasoline ...",
  "text_len": 1433,
  "timestamp": 1658185117948,
  "verified_purchase": true,
  "helpful_vote": 0
}
```

来自 `Office_Products/reviews.base.jsonl` 的首行抽样，长文本已截断：

```json
{
  "dataset": "McAuley-Lab/Amazon-Reviews-2023",
  "category": "Office_Products",
  "user_id": "AFKZENTNBQ7A7V7UXW5JJI6UGRYQ",
  "parent_asin": "B01MZ3SD2X",
  "asin": "B01AHHL4X2",
  "rating": 5.0,
  "title": "Pretty & I love it!",
  "text": "Lovely ink. Writes well. The right amount of wet/dry ...",
  "text_len": 215,
  "timestamp": 1677939345945,
  "verified_purchase": true,
  "helpful_vote": 0
}
```

### 4.4 Review 字段观察

基于 `stats.json` 和历史体检文档：

- 两个类目的 review 关键字段整体非常完整。
- `verified_purchase` 占比很高：
  - Electronics：40,546,884 / 43,886,944，约 92.39%
  - Office_Products：11,999,060 / 12,845,712，约 93.41%
- `text` 为空的记录占比很低：
  - Electronics：41,193 条
  - Office_Products：12,887 条
- 评分明显高分偏置，5 星评论占比高，后续不能简单把所有交互都等价视为强正样本。
- `helpful_vote` 大多数为 0，更适合作为辅助权重或文本质量信号，而不是主标签。
- 时间范围跨度很长，从 1990s 到 2023 年，推荐评估应优先按时间切分，而不是随机切分。

---

## 5. `metadata.base.jsonl` 条目结构

### 5.1 一行代表什么

`metadata.base.jsonl` 中每一行是一条标准化后的商品元数据记录，粒度是 `parent_asin`。它是 review 表的商品侧补充信息，主要用于：

- 商品标题展示
- 类目过滤 / 类目召回
- 内容召回
- 排序特征
- 推荐解释与 RAG grounding

### 5.2 字段清单

| 字段 | 类型 | 是否关键 | 含义 | 生成 / 清洗规则 | 推荐用途 |
| --- | --- | --- | --- | --- | --- |
| `dataset` | string | 否 | 原始数据集名，当前固定为 `McAuley-Lab/Amazon-Reviews-2023` | 由脚本写入固定值 | 数据血缘、跨数据源区分 |
| `category` | string | 是 | 生成时的 Amazon 类目 | 来自 category 参数 | 分类建模、类目路由 |
| `parent_asin` | string | 是 | 父商品 ID，metadata 主键 | 缺失则整条 metadata 被过滤 | 与 review join、商品主键 |
| `title` | string 或 null | 是 | 商品标题 | 原样保留 `record.get("title")` | 展示、文本召回、RAG 商品名 |
| `main_category` | string 或 null | 中 | 商品主类目 | 原样保留 `record.get("main_category")` | 类目过滤、展示、特征 |
| `categories` | list | 中 | 商品类目路径 | 缺失时转为空列表 | 类目召回、层级特征、筛选 |
| `description` | list | 中 | 商品描述文本列表 | 缺失时转为空列表 | 文本语料、RAG、内容召回 |
| `features` | list | 中 | 商品卖点 / 属性文本列表 | 缺失时转为空列表 | 文本特征、解释、RAG |
| `images` | list | 中 | 商品图片 URL 资产，常见字段包括 `thumb`、`large`、`hi_res`、`variant` | 缺失时转为空列表；从 schema v1.1 开始保留 `record.get("images")` | 商品展示、前端 `image_url` 派生、后续视觉 embedding |
| `price` | number / string / null | 低到中 | 商品价格 | 原样保留 `record.get("price")` | 价格过滤、排序特征；但缺失较多 |
| `average_rating` | number 或 null | 中 | 商品平均评分 | 原样保留 `record.get("average_rating")` | 商品质量信号、排序特征 |
| `rating_number` | int 或 null | 中 | 商品评分数量 | 原样保留 `record.get("rating_number")` | 热度 / 置信度信号 |
| `store` | string 或 null | 低到中 | 项目中按“店铺”字段使用；原始语义更接近 Amazon metadata 中的店铺名 / 品牌名 / merchant display name | 原样保留 `record.get("store")` | 店铺偏好、展示、解释 |
| `details` | dict 或 null | 中 | 商品结构化详情属性 | 原样保留 `record.get("details")` | 属性抽取、解释、筛选 |
| `bought_together` | 任意或 null | 低 | 原始共购信息 | 原样保留 `record.get("bought_together")` | 当前产物中基本不可用 |

### 5.3 Metadata 样例

来自 `Electronics/metadata.base.jsonl` 的首行抽样：

```json
{
  "dataset": "McAuley-Lab/Amazon-Reviews-2023",
  "category": "Electronics",
  "parent_asin": "B00MCW7G9M",
  "title": "FS-1051 FATSHARK TELEPORTER V3 HEADSET",
  "main_category": "All Electronics",
  "categories": ["Electronics", "Television & Video", "Video Glasses"],
  "description": ["Teleporter V3 The Teleporter V3 kit sets a new level of value ..."],
  "features": [],
  "images": [
    {
      "thumb": "https://m.media-amazon.com/images/I/41qrX56lsYL._AC_US40_.jpg",
      "large": "https://m.media-amazon.com/images/I/41qrX56lsYL._AC_.jpg",
      "variant": "MAIN",
      "hi_res": null
    }
  ],
  "price": null,
  "average_rating": 3.5,
  "rating_number": 6,
  "store": "Fat Shark",
  "details": {
    "Date First Available": "August 2, 2014",
    "Manufacturer": "Fatshark"
  },
  "bought_together": null
}
```

来自 `Office_Products/metadata.base.jsonl` 的首行抽样，长文本已截断：

```json
{
  "dataset": "McAuley-Lab/Amazon-Reviews-2023",
  "category": "Office_Products",
  "parent_asin": "B001S28Q4Q",
  "title": "Alliance Rubber 07706 Non-Latex Brites File Bands ...",
  "main_category": "Office Products",
  "categories": [
    "Office Products",
    "Office & School Supplies",
    "Tape, Adhesives & Fasteners"
  ],
  "description": ["Alliance Rubber Brites File Bands are durable ..."],
  "features": [
    "REUSABLE: These colored rubber bands are stretchable and reusable ...",
    "EASY STRETCH BANDS: With their easy stretch design ..."
  ],
  "images": [
    {
      "thumb": "https://m.media-amazon.com/images/I/51ON9HgdplL._AC_US40_.jpg",
      "large": "https://m.media-amazon.com/images/I/51ON9HgdplL._AC_.jpg",
      "variant": "MAIN",
      "hi_res": "https://m.media-amazon.com/images/I/81-bwFg+7aL._AC_SL1500_.jpg"
    }
  ],
  "price": 2.68,
  "average_rating": 4.5,
  "rating_number": 665,
  "store": "Alliance",
  "details": {
    "Manufacturer": "Alliance Rubber Company Inc.",
    "Brand": "Alliance",
    "Item Weight": "2 ounces"
  },
  "bought_together": null
}
```

### 5.4 Metadata 字段观察

历史体检结论中记录的关键缺失情况：

| 字段现象 | Electronics | Office_Products | 建议 |
| --- | ---: | ---: | --- |
| `price = null` | 1,083,156，约 67.28% | 424,073，约 59.70% | 不适合作为当前核心特征 |
| `description = []` | 682,678，约 42.41% | 288,511，约 40.61% | 可用但需要空值兜底 |
| `features = []` | 423,003，约 26.28% | 159,820，约 22.50% | 可作为文本特征，但覆盖不满 |
| `categories = []` | 128,428，约 7.98% | 75,637，约 10.65% | 总体可用，仍需空列表处理 |
| `images = []` | 369，约 0.02% | 3,266，约 0.46% | schema v1.1 起保留；可用于展示与视觉特征派生 |
| `bought_together = null` | 100% | 100% | 当前阶段忽略 |
| `title = ""` | 94 条 | 35 条 | 标题几乎全量可用 |

本次抽样前 1000 行也观察到：

- 上游原始 metadata 中 `images` 覆盖率很高，当前 schema v1.1 已在 base 层保留；本地回填后 Electronics 有图 1,609,491 / 1,609,860，Office_Products 有图 707,137 / 710,403。
- `bought_together` 在两个类目抽样中均为 `null`。
- `price` 缺失比例较高。
- `description`、`features`、`categories` 常见为空列表，需要下游特征工程处理空值。
- `details` 是嵌套字典，不同商品的 key 不完全一致，不适合直接作为固定宽表字段使用。

---

## 6. Manifest 与 Stats 条目结构

除了 review 和 metadata 两类主数据文件，base 数据集目录下还有两个管理文件。

### 6.1 `manifest.json`

`manifest.json` 是 base 数据集的入口索引，记录数据来源、schema 版本、类目和每个类目的文件路径。

字段结构：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `dataset` | string | 原始数据集名 |
| `schema_version` | string | base 层 schema 版本 |
| `generated_at` | string | 生成时间，ISO 格式 |
| `categories` | list[string] | 已生成的类目列表 |
| `outputs` | list[object] | 每个类目的输出文件信息 |
| `outputs[].category` | string | 类目名 |
| `outputs[].reviews_path` | string | 对应类目的 review JSONL 路径 |
| `outputs[].metadata_path` | string | 对应类目的 metadata JSONL 路径 |

下游 `rs_core/data/pipelines/recall_clean.py` 默认以 `data/processed/amazon_2023_base/manifest.json` 作为输入入口继续构建 canonical clean 表。

### 6.2 `stats.json`

`stats.json` 是生成阶段的统计摘要，用来快速判断数据规模、过滤情况和文本长度分布。

顶层字段：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `dataset` | string | 原始数据集名 |
| `schema_version` | string | schema 版本 |
| `category_stats` | list[object] | 分类目统计 |
| `totals` | object | 全部类目的汇总统计 |

`category_stats` 中每个类目的字段：

| 字段 | 含义 |
| --- | --- |
| `category` | 类目名 |
| `raw_reviews_seen` | 原始 review 读取行数 |
| `normalized_reviews_kept` | 标准化后保留的 review 行数 |
| `skipped_missing_identity` | 因缺少 `user_id` 或 `parent_asin` 被跳过的 review 数 |
| `distinct_user_count` | 去重用户数 |
| `distinct_parent_asin_count` | 去重父商品数 |
| `verified_counts` | verified / unverified review 数 |
| `text_length_buckets` | review 正文长度分桶 |
| `raw_metadata_seen` | 原始 metadata 读取行数 |
| `normalized_metadata_kept` | 标准化后保留的 metadata 行数 |
| `skipped_missing_parent_asin` | 因缺少 `parent_asin` 被跳过的 metadata 数 |
| `metadata_scope` | metadata 保留范围，当前为 `observed-items` |
| `reviews_path` | review 文件路径 |
| `metadata_path` | metadata 文件路径 |

---

## 7. 字段之间的关系

### 7.1 Review 与 Metadata 的 join

当前最核心的 join 关系：

```text
reviews.base.jsonl.parent_asin == metadata.base.jsonl.parent_asin
```

推荐建模时常见组合：

| 目标 | 主要字段 |
| --- | --- |
| 用户行为序列 | `user_id`, `parent_asin`, `timestamp`, `rating` |
| 正样本构建 | `rating`, `verified_purchase`, `timestamp` |
| 商品展示 | `parent_asin`, `title`, `store`, `main_category`, `price` |
| 文本召回 / RAG | `title`, `description`, `features`, `categories`, review `text` |
| 排序特征 | `average_rating`, `rating_number`, `category`, `verified_purchase`, `helpful_vote`, `text_len` |
| 解释生成 | 商品 `title` / `features` / `description` + review `title` / `text` |

### 7.2 `parent_asin` 与 `asin` 的区别

| 字段 | 所在表 | 粒度 | 当前建议 |
| --- | --- | --- | --- |
| `parent_asin` | review + metadata | 父商品 / 推荐 item | 当前主键，优先使用 |
| `asin` | review | 具体变体 | 暂作辅助字段，不作为第一版主 item 粒度 |

原因：

1. metadata 在 `parent_asin` 粒度上一物一行。
2. review 与 metadata 已按 `parent_asin` 对齐。
3. 直接使用 `asin` 会引入更强稀疏性和 metadata 对齐复杂度。

---

## 8. 下游使用建议

### 8.1 构建推荐样本时的最小字段

如果目标是从 base 层生成用户-物品交互样本，建议最小保留：

```text
user_id
parent_asin
category
timestamp
rating
verified_purchase
helpful_vote
```

可选补充：

```text
asin
review title
review text
text_len
```

### 8.2 构建商品内容表时的最小字段

如果目标是构建商品侧表或 RAG 商品知识库，建议保留：

```text
parent_asin
category
title
main_category
categories
description
features
average_rating
rating_number
store
price
details
```

其中：

- `store` 在本项目后续可直接按“店铺”字段使用，用于店铺偏好、店铺展示和推荐解释；但它不是完整 seller / merchant 实体表，也没有店铺级曝光、点击或转化日志。
- `title` 几乎全量可用，适合作为商品展示和文本检索的核心字段。
- `description` 与 `features` 有一定空缺，但仍是商品知识库的重要文本来源。
- `details` 可用于属性增强，但要先做 key 归一和字段选择。
- `price` 缺失较多，不建议作为第一版强依赖特征。

### 8.3 标签与过滤建议

当前 base 层只保留原始评分和行为信号，不直接定义训练标签。下游可以按任务派生：

| 标签口径 | 示例 | 适用场景 |
| --- | --- | --- |
| 宽松正反馈 | `rating >= 4` | baseline implicit feedback |
| 强正反馈 | `rating >= 4 and verified_purchase == true` | 更干净的召回 / 排序训练 |
| 负反馈 / 弱反馈 | `rating <= 2` | 排序对比、偏好建模 |
| 权重信号 | `helpful_vote`, `rating`, `text_len` | 样本权重、解释质量筛选 |

### 8.4 切分与去重建议

由于数据时间跨度很长，建议：

1. 优先按 `timestamp` 做时间切分，而不是随机切分。
2. 构建用户序列前按 `(user_id, parent_asin, timestamp)` 做精确去重检查。
3. 如果一个用户对同一 `parent_asin` 有多次行为，第一版可保留最近一次。
4. 建模前过滤低频用户和低频商品，降低极端稀疏性。
5. 如只服务近期推荐目标，应考虑时间窗，例如近两年训练、最新三个月测试的当前项目口径。

---

## 9. 当前不建议强依赖的字段

| 字段 | 原因 | 当前建议 |
| --- | --- | --- |
| `price` | 缺失比例高，且不同类目价格分布差异大 | 可用于展示或弱特征，不作为核心 gate |
| `bought_together` | 当前 base 产物中基本全为空 | 暂不用于共购图或召回 |
| `details` 全量 key | 嵌套结构且 key 高度不规则 | 先抽取高频 key，再做结构化特征 |
| `asin` | 变体级粒度更稀疏，metadata 当前按 `parent_asin` 对齐 | 暂不作为主 item id |
| 原始 review `text` 全量拼接 | 文本体量大且长度分布跨度大 | 需要截断、清洗和采样策略 |

---

## 10. SQL raw 表落库建议

如果需要把 base 数据落到本地结构化库，当前建议先进入 raw/base 层，而不是直接污染服务层 `products` / `interactions` 表：

```text
metadata.base.jsonl  -> amazon_items_base
reviews.base.jsonl   -> amazon_reviews_base
```

当前 MySQL raw 表只承接结构化与轻量引用字段：`amazon_items_base` 保留 `images` JSON 作为商品图片 URL 资产，但不下载或存储图片二进制；`amazon_reviews_base` 不再保存完整 `review_title` / `review_text`，而是保存 `text_len`、`has_review_title`、`has_review_text` 和 `review_text_ref`；评论标题和正文后续按 MySQL + ScyllaDB 分层口径进入 ScyllaDB 文本表。这样 MySQL 负责 rating/timestamp/user/item/images 等可筛选、可 join、可聚合或展示派生字段，ScyllaDB 负责长文本和语料大字段。

已补充两个入口：

- 建表 SQL：`scripts/data/sql/create_amazon_base_raw_tables.mysql.sql`
- 导入脚本：`scripts/data/import_amazon_base_to_mysql.py`

推荐 smoke 流程：

```bash
./.venv/Scripts/python.exe scripts/data/import_amazon_base_to_mysql.py --limit 1000 --dry-run
./.venv/Scripts/python.exe scripts/data/import_amazon_base_to_mysql.py --create-schema --limit 1000 --write
```

全量导入前应先确认 MySQL 容器、磁盘空间和资源限制；`reviews.base.jsonl` 总量超过 5600 万行，即使 MySQL 只存结构化字段，也建议先用 `--limit` 分级验证，再决定是否全量导入。服务层、训练层需要的 `products`、`interactions`、`user_features`、`user_store_features` 后续应从 raw 表派生；长文本表与 RAG corpus 后续走 ScyllaDB / 检索索引链路。

---

## 11. 一页总结

当前 `amazon_2023_base` 是 Amazon Reviews 2023 的本地标准化基础数据层，包含两类核心条目：

1. `reviews.base.jsonl`：用户评论 / 用户-商品交互记录，一行一个 review。
2. `metadata.base.jsonl`：商品元数据记录，一行一个 `parent_asin` 商品。

最重要的字段关系是：

```text
user_id 代表用户
parent_asin 代表当前主推荐 item
reviews.parent_asin 可直接 join metadata.parent_asin
```

当前最适合的工程推进方式是：

1. 以 `parent_asin` 为 item 主键。
2. 从 review 表构建用户-物品交互样本。
3. 按时间做切分和去重。
4. 用 metadata 表补充商品标题、类目、文本、评分数、图片 URL 等内容与展示特征。
5. 对 `price`、`bought_together`、嵌套 `details` 等字段保持谨慎，不作为第一版强依赖。

这批 base 数据已经足够支撑后续的召回、排序、RAG 商品知识库和 Agent 推荐解释，但所有全量处理都应采用流式或分块方式。