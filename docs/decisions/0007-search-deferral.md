# ADR-0007：搜索先用 PostgreSQL，延迟引入搜索引擎

- 状态：提议（待技术负责人确认）
- 日期：2026-10-27
- 决策人：待技术负责人确认 `[CONFIRM]`

## 背景

PRD 需要服务者、服务、动态和资讯搜索，但也提出 Elasticsearch/Meilisearch 可选。MVP 重点是交易闭环和可维护性。

## 决策

- `[DESIGN]` 第一阶段使用 PostgreSQL 全文检索、索引和明确的筛选/排序查询；搜索 API 通过 `SearchProvider` 隔离。
- `[DESIGN]` 当查询延迟、相关性、规模或索引重建要求超出阈值时，再接入 Elasticsearch/Meilisearch，不改变业务 API。
- `[DESIGN]` 推荐算法与搜索分离，推荐通过 `RecommendationProvider` 演进。

## 备选方案

- MVP 即引入 Elasticsearch：能力更强但增加部署、同步、数据一致性和运维成本。

## 影响

- 降低初始复杂度；需要设计索引同步和搜索质量验收。

## 风险与缓解

- 风险：PostgreSQL 搜索在规模化后不足。缓解：保留 Provider、索引投影和容量压测。

## 验证

- 搜索结果正确性、游标稳定性、筛选/排序组合、索引补偿和容量压测。

