# 架构

## 分层

```
简体中文卡面原文
      │
      ▼
┌──────────────────────────────────────────────────────────┐
│ ingest/   上游数据 -> 归一化记录                         │
│   ygopro/cdb_reader.py     原生 cards.cdb                │
│   ygopro/ygoprodeck.py     JSON dump                     │
│   ygocdb.py                简体中文文本（官方译文）      │
│   normalize.py             上游记录 -> CardRecord        │
│   id_mapping.py            身份键                        │
│   pipeline.py              原始快照 + upsert             │
└──────────────────────────────────────────────────────────┘
      │  card_text (lang='zh')
      ▼
┌──────────────────────────────────────────────────────────┐
│ effects/   中文 -> 英文枚举                              │
│   units.py        卡面文本 -> EffectUnit                 │
│   clauses.py      EffectUnit -> Clause（角色切分）       │
│   predicates.py   Clause -> Predicate（动作抽取）        │
│   lexicon.py      中文词表（唯一来源）                   │
│   ontology.py     英文枚举（机器协议）                   │
│   selector.py     CardSelector + 结构化数值比较          │
│   extractors.py   LLM 抽取槽位（v1 空实现）              │
│   validator.py    写库前最后一层校验                     │
│   service.py      唯一的 SQL 桥梁                        │
└──────────────────────────────────────────────────────────┘
      │  effect_unit / effect_clause / effect_predicate
      ▼
┌──────────────────────────────────────────────────────────┐
│ db/  SQLite —— 事实来源                                  │
│   migrations/  001_canonical_card.sql                    │
│                003_card_text.sql                         │
│                004_effect_v2.sql（三级效果模型）         │
│   repository.py  canonical card 行的唯一写入者           │
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
│ query/                                                   │
│   planner.py  自然语言 -> Query AST（规则式占位实现）    │
│   parser.py   "race=DRAGON" -> Query AST                 │
│   dsl.py      AST 本体（JSON，与存储无关）               │
│   fields.py   字段注册表 + 枚举校验                      │
└──────────────────────────────────────────────────────────┘
      │  Query AST
      ▼
┌──────────────────────────────────────────────────────────┐
│ Agent / 编排层                                           │
│   agent/tools.py — get_card, search_cards,               │
│                    search_effects, plan_query, …          │
│   （不含数据库业务逻辑；JSON 进，JSON 出）                │
└──────────────────────────────────────────────────────────┘
```

## 数据流

1. **导入**：把不可变原始快照写入 `data/raw`，登记一条 `raw_source`，每张卡的上游记录原文存入 `raw_card_record`，再 upsert canonical `card` 行。重复执行是幂等的。
2. **中文文本**：`ingest/ygocdb.py` 从 `cards.zip` 取官方简体中文文本，写入 `card_text(lang='zh')`。中文缺失的卡不产出效果，而不是退回英文猜。
3. **效果构建**：`card_text` → `EffectUnit` → `Clause` → `Predicate`，落到三张表。过程确定且成本低，所以「重建」是常规操作而非迁移。
4. **查询**：自然语言（planner）或紧凑过滤串（parser）统一转成 Query AST。
5. **结构化检索**：把 AST 编译成参数化 SQL，返回卡片以及命中该卡的效果原文。
6. **校验**：回读 `effect_unit.raw_text`——每条命中都自带原始措辞，可直接人眼核验。

## 设计决策

| 决策 | 理由 |
| --- | --- |
| SQLite 是唯一事实库 | 数据量小（约 1.5 万张卡）且天然关系型，不需要 Postgres / Elasticsearch |
| 中文是源语言，英文枚举是机器协议 | 面向简体中文 OCG 环境；词表集中一处，检索跑在稳定枚举上 |
| 不「先翻译成英文再解析」 | 翻译会丢掉 COST / CONDITION 的语序信息，而中文卡面本身就写着 |
| `card_id` 是内部主键 | 没有任何外部 id 稳定到可以充当永久主键 |
| `raw_card_record` 保留上游原文 | 任何一次导入都能离线重新解析或审计 |
| 效果切成 unit → clause → predicate 三级 | 「cost 是除外、处理是特殊召唤」压平成一列表达不了 |
| 索引粒度是 `unit_id` | 避开「一张卡 = 一段 embedding」的陷阱；向量命中能落到具体某条效果 |
| `UNKNOWN` 是一等状态 | 解析失败绝不能变成「这张卡没有该效果」 |
| NL 与 SQL 之间是 Query AST | 同一个查询可以分别交给 structured / FTS / semantic 后端 |
| 用嵌套 `EXISTS` 而非扁平 join | 全库实测 68s -> 0.1s |
| parser 优先走确定性规则 | 便宜、可测试、可复现；LLM 抽取是附加层而非基座 |

## 模块边界

- `ingest/` 不直接写 SQL——一律调用 `db/repository.py`。
- `effects/` 不感知 SQL；`effects/service.py` 是唯一桥梁。
- `effects/lexicon.py` + `effects/ontology.py` 是中文词表的唯一来源；
  parser 模块里不允许出现中文字面量。
- `retrieval/` 只读。
- `query/` 不感知 SQL；翻译职责归 `retrieval/structured/compiler.py`。
- `agent/` 不含数据库逻辑——工具只做转发并返回 JSON。

规则解析器、LLM 抽取器、validator 三层彼此独立，任何一层都能单独替换和测试。
**v1 的 LLM 层是空实现**，接口与标注位置已就位。

## 后续阶段规划

| Phase | 内容 |
| --- | --- |
| 4 | 卡名 + 效果文本的 FTS5，包装为 `fulltext_search` |
| 5 | Hybrid Retrieval：structured ⊕ FTS ⊕ semantic，含合并 / 重排 |
| 6 | Semantic Retrieval，以 `unit_id` 为键；未配置 embedding 模型时走确定性 fallback |
| 7 | LLM Query Planner 替换规则式 planner；长句效果抽取交给 LLM（填上 v1 留出的槽位） |
| 8 | `search_rulings` / FAQ 接口（系统中唯一允许联网的部分） |

已知待办：FTS5 的 trigram 分词器最短 3 字符，中文两字词（「除外」「龙族」）
建不出索引——Phase 4 需要换分词方案。
