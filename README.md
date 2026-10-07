# YGOLookup

一个基于 **YGOPro / Project Ignis 本地卡牌数据**的「游戏王智能卡牌检索系统」。

目标不是做关键词匹配，而是让用户用自然语言提出复合效果约束，例如：

- 找所有 4 星以下暗属性恶魔族怪兽
- 找能够从额外卡组特殊召唤龙族怪兽的卡
- 找能够以「除外墓地怪兽」为 COST、并从卡组特殊召唤怪兽的卡
- 找能够支援某个主题 / 系列的旧卡

系统的**事实来源永远是本地 SQLite 数据库**。向量 / 语义检索只作为辅助召回层，
不允许成为事实数据库。

---

## 架构原则

```
LLM / Agent
    ↓
Query Planning
    ↓
Hybrid Retrieval ──┬── Structured SQL Search   (核心，保证正确性)
                   ├── Full Text Search (FTS5)
                   └── Semantic / Vector Search (可选)
    ↓
Candidate Effects / Cards
    ↓
回读原始效果文本校验
    ↓
Result
```

1. SQLite 是主事实数据库。
2. Vector DB / Embedding 只是辅助召回层。
3. **不采用「一张卡 = 一段 embedding」** 的设计；索引粒度是 `unit_id`（一条效果）。
4. **简体中文是源语言，英文枚举是机器协议。** effect 层只读中文卡面原文。
5. 卡面文本切成 `EffectUnit`（① / ② / 卡名限制 / 素材行）。
6. `EffectUnit` 切成 `Clause`，带角色：condition / cost / target / resolution / restriction / unknown。
7. `Clause` 切成 `Predicate`：subject / action / object / source_zone / destination_zone / modifiers。
8. 自然语言不直接生成 SQL，必须经过 Query AST。
9. 最终结果回读原始效果文本进行核验。
10. 第一阶段不实现完整游戏规则引擎。

---

## 目录结构

```
├── pyproject.toml / requirements.txt
├── data/
│   ├── raw/          # 不可变原始数据快照（cdb / API dump），git-ignored
│   └── processed/    # 生成的 SQLite 数据库，git-ignored
├── src/ygolookup/
│   ├── config.py
│   ├── db/           # schema / 连接 / 迁移 / 模型
│   ├── ingest/       # 数据源适配器 + normalize + id_mapping + ygocdb
│   ├── effects/      # units / clauses / predicates / lexicon / ontology /
│   │                 # selector / extractors / validator / service
│   ├── retrieval/    # structured / fulltext / semantic / hybrid
│   ├── query/        # Query AST (DSL) / planner
│   ├── agent/        # tool surface for an LLM orchestrator
│   └── cli.py
├── tests/
└── docs/
    ├── architecture.md
    ├── schema.md
    ├── query-dsl.md
    └── chinese-text-spec.md   # 中文 OCG 文本规范（parser 的判据来源）
```

---

## 安装

运行时只依赖 Python 标准库（sqlite3 / json / dataclasses）。

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # 仅 pytest
```

可选环境变量（复制 `.env.example` 为 `.env`）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `YGO_DB_PATH` | `data/processed/ygolookup.db` | canonical SQLite 路径 |
| `YGO_RAW_DIR` | `data/raw` | 原始数据快照目录 |
| `YGO_YGOPRODECK_API` | `https://db.ygoprodeck.com/api/v7/cardinfo.php` | JSON 数据源 |
| `YGO_EMBEDDING_MODEL` | 空 | 空则使用确定性 fallback 语义后端 |

---

## 数据初始化

```bash
# 从 YGOProDeck JSON 源抓取原始快照并导入（首次运行会联网）
python -m ygolookup.cli ingest --source ygoprodeck

# 从本地 YGOPro cards.cdb 导入
python -m ygolookup.cli ingest --source cdb --path /path/to/cards.cdb

# 下载 ygocdb 全量简体中文文本并写入 card_text
python -m ygolookup.cli ingest --source ygocdb

# 查看数据库统计
python -m ygolookup.cli stats
```

---

效果构建（导入中文文本之后必须跑一次；它是幂等的全量重建）：

```bash
python -m ygolookup.cli effects
```

---

## 示例查询

```bash
# 结构化字段查询（裸字段名默认属于 card.*）
python -m ygolookup.cli search --filter race=DRAGON --filter attribute=DARK --filter "level<=4"

# 效果检索（effect.* / clause.* 会自动包成 exists 块）
python -m ygolookup.cli search --filter effect.action=SPECIAL_SUMMON \
                               --filter effect.source_zone=EXTRA_DECK \
                               --filter effect.object_race=DRAGON

# 以「除外墓地」为 COST 的卡
python -m ygolookup.cli search --filter clause.role=COST \
                               --filter effect.action=BANISH \
                               --filter effect.source_zone=GRAVEYARD

# 自然语言（规则式 planner）
python -m ygolookup.cli search --nl "找能够从额外卡组特殊召唤龙族怪兽的卡"

# Query AST（JSON 文件），--explain 只打印 AST
python -m ygolookup.cli search --query-file query.json --explain

# 查看单张卡的解析结果
python -m ygolookup.cli effects-show "Junk Synchron"
```

完整的 AST 字段与运算符见 [docs/query-dsl.md](docs/query-dsl.md)。

---

## 项目状态

当前数据库（本地已构建）：

| 指标 | 数量 |
| --- | --- |
| 卡片 | 14,597 |
| 有简体中文文本的卡 | 14,237（97.5%） |
| EffectUnit | 32,196 |
| Clause | 68,863 |
| Predicate | 79,007（其中 47,350 条判定了动作，59.9%） |
| 校验错误 | 0 |

`parse_status`：`OK` 21,295 / `PARTIAL` 5,858 / `UNRESOLVED` 5,043。

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| Phase 0 | 仓库骨架 / 测试框架 / 文档结构 | 完成 |
| Phase 1 | Canonical Card Database + cdb / JSON 导入器 | 完成 |
| Phase 2 | Effect 数据模型 + splitter + 确定性 parser + 三值 schema | 完成 |
| Phase 3 | Query DSL + Structured Retrieval + Agent 工具层 | 完成 |
| Phase A | 中文 OCG 文本规范 + ygocdb 数据源 | 完成 |
| Phase B–F | 中文三级效果管道（unit → clause → predicate）+ 落库 + validator | 完成 |
| Phase G | 中文回归 fixture + 测试 | 完成 |
| Phase H | Query 层适配 + CLI + 文档 | 完成 |
| Phase 4 | FTS5 全文检索 | 待开始 |
| Phase 5 | Hybrid Retrieval（structured ⊕ FTS ⊕ semantic） | 待开始 |
| Phase 6 | Semantic Retrieval（以 `unit_id` 为索引粒度） | 待开始 |
| Phase 7 | LLM Query Planner / LLM 效果抽取（v1 已留空槽位） | 待开始 |
| Phase 8 | `search_rulings` 裁定接口（唯一允许联网的部分） | 待开始 |

---

## 已知限制

- 导入源为 YGOProDeck JSON（卡面元数据）+ ygocdb（简体中文文本）；
  `cards.cdb` 读取器已实现并用合成 cdb 做过端到端测试，但未用真实官方
  `cards.cdb` 验证（无公开直链镜像）。
- 360 张卡没有中文文本（124 张 SKILL、106 张 TOKEN 为主），因此不产出任何效果。
- Effect parser 覆盖高频中文措辞，**不处理**：连锁速度、伤害步骤、错过时点、
  代替 / 持续效果、完整召唤手续、完整裁定。
- OR 条件（「龙族或者战士族」）目前只记录第一个分支，未拆成多条候选谓词。
- 指代消解只处理最简形态（同一 unit 内「那只怪兽」回指前一个 TARGET 或产物），
  完整规则图推理不在 v1 范围内。
- 未解析出的字段一律标记为 `UNKNOWN`（`action IS NULL`），**不会**被当作
  「卡片没有该效果」。
- Planner 是规则式占位实现；遇到无法映射的表述会返回 `unmatched`，应回退到
  FTS / 语义检索。
- `fulltext_search` / `semantic_search` 接口已声明，尚未实现。
- FTS5 的 trigram 分词器最短 3 字符，中文两字词（「除外」「龙族」）建不出
  索引——Phase 4 需要换分词方案。
