# NestLinker World Model Data

韩国外国租客决策世界模型的数据底座。这个仓库优先解决四件事：来源可追溯、采集可复现、时间口径明确、模型不会把“事实 / 估计 / 教学模拟”混在一起。

## 当前覆盖

截至 2026-09-01，目录登记 30 个公开来源；首个可复核快照包含 6 个文件、9,935 条记录。覆盖数量、限制与下一批采集顺序见 `docs/COVERAGE.md`。

- 租赁成交：国土交通部 RTMS，按住宅类型、区、月份采集。
- 人口与外国人：行政安全部居民人口、法务部登记/居所外国人统计。
- 合法经营与建筑核验：持牌中介、建筑物台账、考试院消防登记的来源契约。
- 风险基线：HUG 保证事故与返还保证、租赁价格指数。
- 行动约束：大学、地铁、通勤、外国人登记及租赁法律指引。
- 环境上下文：洪涝、空气与必要生活设施等候选数据。

`catalog/datasets.json` 是全量数据源目录。`data/snapshots/` 只保存已经通过许可、隐私和质量门禁的快照。目录中访问方式为 `api_key` 或状态为 `manual_review` 的来源不会因为“能下载”就自动进入模型。

“全量目录”是对当前调查范围的可扩展登记，不代表已穷尽互联网；新增来源必须保留发现日期、官方落地页和使用限制。

## 快速使用

```bash
python -m unittest discover -s tests -v
python -m worldmodel_data validate
python -m worldmodel_data catalog --category market
```

从 NestLinker 主仓导入已有的公开数据派生快照：

```bash
python -m worldmodel_data import-nestlinker \
  --source-root ../nestlinker-source \
  --snapshot-date 2026-09-01
```

拉取 RTMS 原始数据需要在本地设置 `DATA_GO_KR_SERVICE_KEY`：

```bash
export DATA_GO_KR_SERVICE_KEY='your-decoding-key'
python -m worldmodel_data fetch-rtms --months 3 --seoul-only
```

RTMS 原始响应写入 gitignore 的 `data/raw/`；经过最小化、去标识和字段标准化后，才能发布到 `data/snapshots/`。

## 数据契约

每个快照必须有 `manifest.json`，至少记录：

- `source_id` 与官方落地页；
- 抓取时间、数据时点和地理范围；
- 原始或派生状态；
- 文件 SHA-256、字节数和记录数；
- 适用限制及不得做出的推断。

世界模型消费数据时必须输出 `observed | modeled | synthetic` 标签；本仓库只提供 `observed` 和明确标记的 `derived_observed` 数据，不保存模型生成概率。

## 许可

仓库代码使用 MIT。数据不随代码重新授权，各文件继续受原始提供者条款及韩国公共著作物许可约束，详见 `catalog/datasets.json` 和快照 manifest。
