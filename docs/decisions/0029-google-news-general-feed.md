# ADR-0029：Google News 默认同步综合最新资讯

- 状态：已接受
- 日期：2026-11-06
- 决策人：项目负责人

## 背景

原 Google News 来源地址使用 `q=when:1d`。Google 将该值识别为搜索关键词，实际返回零条资讯；同步过程因没有网络或解析异常而显示成功，但不会创建任何文章。

## 决策

- `[PRD]` 当前阶段 Google News 默认获取综合最新资讯，不按管理员输入关键词搜索。
- `[DESIGN]` `GOOGLE_NEWS_ZH` 的订阅地址调整为 Google News 中文综合 RSS。
- `[DESIGN]` 通过新增数据迁移更新已有来源配置，不修改历史迁移，保证新环境和已有开发库最终配置一致。
- `[DESIGN]` 同步结果继续通过 `fetched_count`、`created_count`、`updated_count` 和 `skipped_count` 表达；零条结果不代表数据库写入失败。

## 后续事项

- `[CONFIRM]` 如果后续需要按关键词搜索 Google News，应单独设计关键词 URL 编码、必填规则、搜索来源配置和零结果状态，不与综合最新来源混用。
- `[CONFIRM]` 外部 RSS 的可访问性、使用条款和版权仍由部署环境与管理员负责确认。

## 验证

- 验证迁移应用后 `GOOGLE_NEWS_ZH.feed_url` 指向综合 RSS。
- 运行资讯同步测试、迁移检查、Ruff 和完整自动化测试。
