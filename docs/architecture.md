# 架构

## 分层

```
自然语言
      │
      ▼
┌──────────────────────────────────────────────────────────┐
│ Agent / 编排层                                           │
│   agent/tools.py — get_card, search_cards,               │
│                    search_effects, plan_query, …          │
│   （不含数据库业务逻辑；JSON 进，JSON 出）                │
└──────────────────────────────────────────────────────────┘
      │  Query AST
      ▼
┌──────────────────────────────────────────────────────────┐
│ query/                                                   │
│   planner.py  自然语言 -> Query AST（规则式占位实现）    │
│   parser.py   "race=DRAGON" -> Query AST                 │
│   dsl.py      AST 本体（JSON，与存储无关）               │
│   fields.py   字段注册表 + 枚举校验                      │
└──────────────────────────────────────────────────────────┘
      │
      ▼
┌──────────────────────────────────────────────────────────┐
│ retrieval/                                               │
│   structured/  compiler.py（AST -> SQL）+ search.py      │
│   fulltext/    FTS5            （规划中）                │
│   semantic/    effect embedding（规划中，可选）          │
│   hybrid/      合并 + 重排     （规划中）                │
└──────────────────────────────────────────────────────────┘
      │
      ▼
┌──────────────────────────────────────────────────────────┐
│ db/  SQLite —— 事实来源                                  │
│   migrations/  001_canonical_card.sql, 002_effect.sql    │
│   repository.py  canonical card 行的唯一写入者           │
└──────────────────────────────────────────────────────────┘
      ▲
      │
┌──────────────────────────────────────────────────────────┐
│ ingest/   上游数据 -> 归一化记录                         │
│   ygopro/cdb_reader.py     原生 cards.cdb                │
│   ygopro/ygoprodeck.py     JSON dump                     │
│   normalize.py             上游记录 -> CardRecord        │
│   id_mapping.py            身份键                        │
│   pipeline.py              原始快照 + upsert             │
└──────────────────────────────────────────────────────────┘
```

## 数据流

1. **导入**：把不可变原始快照写入 `data/raw`，登记一条 `raw_source`，每张卡的上游记录原文存入 `raw_card_record`，再 upsert canonical `card` 行。重复执行是幂等的。
2. **效果构建**：把 `card.raw_text` 切成 `effect` 段，每段解析出若干 `effect_predicate` 行。过程确定且成本低，所以「重建」是常规操作而非迁移。
3. **查询**：自然语言（planner）或紧凑过滤串（parser）统一转成 Query AST。
4. **结构化检索**：把 AST 编译成参数化 SQL，返回卡片以及命中该卡的效果原文。
5. **校验**：回读 `effect.raw_text`——每条命中都自带原始措辞，可直接人眼核验。

## 设计决策

| 决策 | 理由 |
| --- | --- |
| SQLite 是唯一事实库 | 数据量小（约 1.5 万张卡）且天然关系型，不需要 Postgres / Elasticsearch |
| `card_id` 是内部主键 | 没有任何外部 id 稳定到可以充当永久主键 |
| `raw_card_record` 保留上游原文 | 任何一次导入都能离线重新解析或审计 |
| 一张卡 -> 多个 effect，而不是一整段文本 | 「这张卡有一个效果是……」才是真实的查询形态 |
| 索引粒度是 `effect_id` | 避开「一张卡 = 一段 embedding」的陷阱；向量命中能落到具体某条效果 |
| `UNKNOWN` 是一等状态 | 解析失败绝不能变成「这张卡没有该效果」 |
| NL 与 SQL 之间是 Query AST | 同一个查询可以分别交给 structured / FTS / semantic 后端 |
| 用嵌套 `EXISTS` 而非扁平 join | 全库实测 68s -> 0.1s |
| parser 优先走确定性规则 | 便宜、可测试、可复现；LLM 抽取是附加层而非基座 |

## 模块边界

- `ingest/` 不直接写 SQL——一律调用 `db/repository.py`。
- `retrieval/` 只读。
- `effects/` 不感知 SQL；`effects/service.py` 是唯一桥梁。
- `query/` 不感知 SQL；翻译职责归 `retrieval/structured/compiler.py`。
- `agent/` 不含数据库逻辑——工具只做转发并返回 JSON。

## 后续阶段规划

| Phase | 内容 |
| --- | --- |
| 4 | 卡名 + 效果文本的 FTS5，包装为 `fulltext_search` |
| 5 | Hybrid Retrieval：structured ⊕ FTS ⊕ semantic，含合并 / 重排 |
| 6 | Semantic Retrieval，以 `effect_id` 为键；未配置 embedding 模型时走确定性 fallback |
| 7 | LLM Query Planner 替换规则式 planner；长句效果抽取交给 LLM |
| 8 | `search_rulings` / FAQ 接口（系统中唯一允许联网的部分） |
