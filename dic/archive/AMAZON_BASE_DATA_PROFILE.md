# Amazon Base 数据体检报告

## 1. 范围说明

本报告针对当前已生成的 Amazon base 数据产物进行体检，数据位置为：

- `data/processed/amazon_2023_base/Electronics/reviews.base.jsonl`
- `data/processed/amazon_2023_base/Electronics/metadata.base.jsonl`
- `data/processed/amazon_2023_base/Office_Products/reviews.base.jsonl`
- `data/processed/amazon_2023_base/Office_Products/metadata.base.jsonl`
- `data/processed/amazon_2023_base/manifest.json`
- `data/processed/amazon_2023_base/stats.json`

当前数据粒度的核心约定是：

- 用户主键：`user_id`
- 物品主键：`parent_asin`
- 变体级物品 ID：`asin`

也就是说，当前这批 base 数据更适合先做 **以 `parent_asin` 为 item 粒度** 的推荐建模。

---

## 2. 一页结论

### 2.1 当前处于什么阶段

当前已经完成 **基础数据准备 / base clean**，可以进入下一步的：

- 交互样本构建
- 去重与频次过滤
- 时间切分 train / valid / test
- baseline 召回构建

### 2.2 这批数据是否适合继续做推荐

适合，而且很适合作为项目第一版的推荐底座数据，原因有三点：

1. `reviews` 与 `metadata` 已经在 `parent_asin` 粒度上对齐
2. 两个类目数据量足够大，能够支撑 baseline 召回和后续排序
3. review 字段结构很干净，关键主键字段没有缺失

### 2.3 建模时最重要的三个提醒

1. **先用 `parent_asin` 做 item 主键，不要一开始就用 `asin`。**
2. **先做用户-物品交互样本，不要直接跳复杂召回模型。**
3. **先做按时间切分和去重，再讨论召回效果。**

---

## 3. 数据规模总览

### 3.1 类目规模

| Category | Reviews | Metadata | Distinct Users | Distinct `parent_asin` |
| --- | ---: | ---: | ---: | ---: |
| Electronics | 43,886,944 | 1,609,860 | 18,286,191 | 1,609,860 |
| Office_Products | 12,845,712 | 710,403 | 7,613,158 | 710,403 |

补充观察：

- `metadata` 行数与 `distinct_parent_asin_count` 完全一致，说明当前产物在 `parent_asin` 粒度上是一物一行。
- 这意味着后续做 review × metadata join 时，当前 base 数据可以视为 **100% 可对齐**。

### 3.2 文件体量

| File | Approx Size |
| --- | ---: |
| `Electronics/reviews.base.jsonl` | 24.80 GB |
| `Electronics/metadata.base.jsonl` | 3.03 GB |
| `Office_Products/reviews.base.jsonl` | 6.44 GB |
| `Office_Products/metadata.base.jsonl` | 1.25 GB |

这说明后续处理应优先采用：

- 流式读取
- 分块处理
- parquet 化或中间表落盘

不要默认全量一次性读入内存。

---

## 4. 表结构与字段含义

### 4.1 `reviews.base.jsonl`

字段如下：

- `dataset`
- `category`
- `user_id`
- `parent_asin`
- `asin`
- `rating`
- `title`
- `text`
- `text_len`
- `timestamp`
- `verified_purchase`
- `helpful_vote`

字段角色建议：

| 字段 | 角色 | 说明 |
| --- | --- | --- |
| `user_id` | 用户主键 | 构建用户交互历史 |
| `parent_asin` | 推荐 item 主键 | 当前最适合做召回/排序的物品粒度 |
| `asin` | 变体级辅助字段 | 后续细粒度建模可再引入 |
| `rating` | 显式反馈 | 可转成正负样本或偏好强度 |
| `timestamp` | 时间序列字段 | 用于时间切分和最近行为 |
| `verified_purchase` | 行为质量信号 | 可作为高质量交互标记 |
| `helpful_vote` | 内容质量信号 | 可用于后续权重设计 |
| `text`, `title`, `text_len` | 文本内容 | 用于内容理解和后续内容召回 |

### 4.2 `metadata.base.jsonl`

字段如下：

- `dataset`
- `category`
- `parent_asin`
- `title`
- `main_category`
- `categories`
- `description`
- `features`
- `price`
- `average_rating`
- `rating_number`
- `store`
- `details`
- `bought_together`

字段角色建议：

| 字段 | 角色 | 说明 |
| --- | --- | --- |
| `parent_asin` | 物品主键 | 与 review 对齐的 join key |
| `title`, `description`, `features` | 内容特征 | 适合后续做内容召回/文本特征 |
| `categories`, `main_category` | 类目特征 | 适合类目召回与过滤 |
| `average_rating`, `rating_number` | 商品质量信号 | 可作为排序或规则特征 |
| `price` | 价格特征 | 缺失较多，不适合当前做核心特征 |
| `store`, `details` | 辅助属性 | 可用于解释或补充特征 |
| `bought_together` | 当前基本不可用 | 当前产物里全部为空 |

---

## 5. Review 表体检

## 5.1 结构完整性

两个类目的 `reviews.base.jsonl` 都没有发现关键字段缺失：

- `user_id`
- `parent_asin`
- `asin`
- `rating`
- `text_len`
- `timestamp`
- `verified_purchase`
- `helpful_vote`

这说明脚本的 base clean 已经把主键不完整的记录清掉了，当前 review 表结构非常整齐。

### 5.2 评分分布

#### Electronics

| Rating | Count | Share |
| --- | ---: | ---: |
| 0.0 | 2 | ~0.00% |
| 1.0 | 5,358,800 | 12.21% |
| 2.0 | 2,257,604 | 5.14% |
| 3.0 | 2,883,065 | 6.57% |
| 4.0 | 5,557,725 | 12.66% |
| 5.0 | 27,829,748 | 63.41% |

#### Office_Products

| Rating | Count | Share |
| --- | ---: | ---: |
| 0.0 | 1 | ~0.00% |
| 1.0 | 1,353,519 | 10.54% |
| 2.0 | 589,120 | 4.59% |
| 3.0 | 799,194 | 6.22% |
| 4.0 | 1,400,675 | 10.90% |
| 5.0 | 8,703,203 | 67.75% |

观察：

- 两个类目都明显 **高分偏置**。
- 5 星评论占比很高，说明如果直接把所有交互都当正样本，样本噪声会比较大。
- 后续做 implicit feedback 时，建议至少比较两种口径：
  - `rating >= 4` 作为正反馈
  - `verified_purchase == true and rating >= 4` 作为更强正反馈

### 5.3 Verified Purchase 分布

| Category | Verified | Unverified |
| --- | ---: | ---: |
| Electronics | 40,546,884 (92.39%) | 3,340,060 (7.61%) |
| Office_Products | 11,999,060 (93.41%) | 846,652 (6.59%) |

观察：

- 两个类目都以 verified review 为主。
- 这给后续构建高质量交互样本提供了一个非常好的过滤信号。

### 5.4 文本字段情况

| Category | Empty `text` | Share | Mean `text_len` | Max `text_len` |
| --- | ---: | ---: | ---: | ---: |
| Electronics | 41,193 | 0.09% | 241.33 | 35,208 |
| Office_Products | 12,887 | 0.10% | 175.37 | 33,432 |

补充：

- `Electronics` 中 `title` 仅发现 1 条空字符串。
- `Office_Products` 中未观察到空 `title`。

观察：

- review 文本总体可用，空文本比例很低。
- 文本长度跨度很大，说明后续如果做文本建模，需要考虑截断和清理策略。
- 目前 `text_len` 已是现成特征，可直接用于规则或分析。

### 5.5 Helpful Vote 分布

#### Electronics

- `helpful_vote = 0`: 34,465,185
- `helpful_vote = 1`: 4,999,800
- `helpful_vote = 2-4`: 2,809,662
- `helpful_vote = 5-9`: 862,291
- `helpful_vote >= 10`: 750,006
- 非 0 helpful 占比：21.47%
- 最大值：46,841

#### Office_Products

- `helpful_vote = 0`: 10,209,032
- `helpful_vote = 1`: 1,450,109
- `helpful_vote = 2-4`: 784,762
- `helpful_vote = 5-9`: 222,702
- `helpful_vote >= 10`: 179,107
- 非 0 helpful 占比：20.53%
- 最大值：41,687

观察：

- `helpful_vote` 明显稀疏，大多数记录为 0。
- 它更适合作为加权信号，而不是主监督标签。

### 5.6 时间范围

| Category | Min Timestamp | Max Timestamp |
| --- | --- | --- |
| Electronics | 1996-11-18T16:58:00+00:00 | 2023-09-13T17:26:21.867000+00:00 |
| Office_Products | 1998-10-12T04:07:40+00:00 | 2023-09-12T20:49:01.607000+00:00 |

观察：

- 时间跨度非常长，包含早期历史评论。
- 做推荐样本时不建议随机切分，应该做 **按时间切分**。
- 还应考虑设定时间窗，避免过早年代的行为过度影响当前建模。

### 5.7 重复交互风险

在前 2,000,000 行样本里，按 `(user_id, parent_asin, timestamp)` 检查到的精确重复数量为：

| Category | Duplicate Count | Share in Sample |
| --- | ---: | ---: |
| Electronics | 5,843 | 0.29% |
| Office_Products | 6,628 | 0.33% |

说明：

- 这里是样本内精确统计，不是全量精确去重结果。
- 但它已经说明 **重复交互不是零**。
- 后续样本构建时，建议至少做一次：
  - 同一 `user_id + parent_asin` 保留最后一次交互
  - 或同一 `user_id + parent_asin + timestamp` 精确去重

---

## 6. Metadata 表体检

### 6.1 结构完整性

两个类目的 `metadata.base.jsonl` 都保持了一致 schema，且 `parent_asin` 全量存在，可直接用于与 review 表对齐。

### 6.2 关键缺失与空值

#### Electronics

| Field | Missing / Empty | Share |
| --- | ---: | ---: |
| `price = null` | 1,083,156 | 67.28% |
| `main_category = null` | 106,330 | 6.60% |
| `store` null/empty | 9,522 | 0.59% |
| `description = []` | 682,678 | 42.41% |
| `features = []` | 423,003 | 26.28% |
| `categories = []` | 128,428 | 7.98% |
| `details = {}` | 21,139 | 1.31% |
| `bought_together = null` | 1,609,860 | 100.00% |
| `title = ""` | 94 | 0.01% |

#### Office_Products

| Field | Missing / Empty | Share |
| --- | ---: | ---: |
| `price = null` | 424,073 | 59.70% |
| `main_category = null` | 23,940 | 3.37% |
| `store` null/empty | 12,245 | 1.72% |
| `description = []` | 288,511 | 40.61% |
| `features = []` | 159,820 | 22.50% |
| `categories = []` | 75,637 | 10.65% |
| `details = {}` | 10,343 | 1.46% |
| `bought_together = null` | 710,403 | 100.00% |
| `title = ""` | 35 | 0.00% |

观察：

- `price` 缺失很多，不适合当前作为核心建模特征。
- `description`、`features` 虽然有一定空缺，但仍然是可用的内容特征来源。
- `bought_together` 在当前产物里完全为空，当前阶段可以直接忽略。
- `title`、`store`、`main_category` 的可用性总体较高。

---

## 7. 对推荐建模意味着什么

### 7.1 当前最适合的 item 粒度

当前最适合的 item 粒度是：`parent_asin`

原因：

1. review 与 metadata 已围绕它对齐
2. `metadata` 是严格的一物一行
3. 相比 `asin`，`parent_asin` 稀疏度更低，更适合先做 baseline

### 7.2 当前最适合先做的样本表

建议下一步先产出一张 **用户-物品交互样本表**，核心字段至少包括：

- `user_id`
- `parent_asin`
- `timestamp`
- `rating`
- `verified_purchase`
- `helpful_vote`
- `category`

如果需要附带内容特征，再 join：

- `title`
- `main_category`
- `categories`
- `description`
- `features`
- `average_rating`
- `rating_number`

### 7.3 当前最应该先做的处理

建议顺序：

1. 按 `user_id + parent_asin` 做去重策略设计
2. 过滤低频用户 / 低频商品
3. 按时间排序并切分 train / valid / test
4. 先做一个最小 baseline 召回
   - 热门召回
   - ItemCF
   - 类目召回
5. 再考虑文本侧内容召回

### 7.4 当前不建议立即重投入的方向

当前不建议一开始就重投入在：

- 直接用 `asin` 做主 item 粒度
- 直接上复杂双塔召回
- 把 `price` 当成核心特征
- 依赖 `bought_together` 构建共现图

原因是这些方向在当前数据状态下都不是最稳的起点。

---

## 8. 下一步执行建议

### 8.1 最小闭环方案

下一步建议先做：

1. 生成交互样本表
2. 做去重和频次过滤
3. 做时间切分
4. 产出 baseline 召回评估集

### 8.2 样本构建时建议验证的几个问题

- 每个用户保留几次行为最合适
- 是否只把 `rating >= 4` 当正反馈
- 是否引入 `verified_purchase` 作为正反馈过滤
- 是否按类目分别建模，还是先做混合建模
- 是否需要丢弃过旧行为

---

## 9. 总结

这批 Amazon base 数据已经具备继续往推荐建模推进的条件。

它的优点是：

- review 主键完整
- metadata 与 review 对齐稳定
- 数据量足够大
- 文本和类目特征已经可用

它当前最适合承接的下一步不是直接上复杂模型，而是先完成：

- 交互样本构建
- 去重
- 频次过滤
- 时间切分
- baseline 召回

如果后续要保持工程推进稳定，建议始终围绕一句话：

**先把 `parent_asin` 粒度的用户-物品交互闭环做出来，再扩展到更复杂的召回和排序。**
