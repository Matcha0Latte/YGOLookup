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
3. **不采用「一张卡 = 一段 embedding」** 的设计；索引粒度是 `effect_id`。
4. 卡片效果必须拆分为 `Effect`。
5. `Effect` 进一步结构化为 action / source / destination / target / cost / condition / restriction。
6. 自然语言不直接生成 SQL，必须经过 Query AST。
7. 最终结果回读原始效果文本进行核验。
8. 第一阶段不实现完整游戏规则引擎。

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
│   ├── ingest/       # 数据源适配器 + normalize + id_mapping
│   ├── effects/      # splitter / parser / ontology / validator
│   ├── retrieval/    # structured / fulltext / semantic / hybrid
│   ├── query/        # Query AST (DSL) / planner
│   ├── agent/        # tool surface for an LLM orchestrator
│   └── cli.py
├── tests/
└── docs/
    ├── architecture.md
    ├── schema.md
    └── query-dsl.md
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

# 查看数据库统计
python -m ygolookup.cli stats
```

---

## 示例查询

```bash
# 结构化字段查询
python -m ygolookup.cli search --filter race=DRAGON --filter attribute=DARK --filter "level<=4"

# Query DSL（JSON）
python -m ygolookup.cli search --query-file examples/query.json
```

---

## 项目状态

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| Phase 0 | 仓库骨架 / 测试框架 / 文档结构 | 完成 |
| Phase 1 | Canonical Card Database + 导入器 | 进行中 |
| Phase 2 | Effect 数据模型 + splitter + 结构化 schema | 待开始 |
| Phase 3 | Query DSL + Structured Retrieval | 待开始 |
| Phase 4+ | FTS5 / Hybrid / Semantic / Agent Tools / LLM Planner | 规划中 |

---

## 已知限制

- 当前导入源为 YGOProDeck JSON；`cards.cdb` 读取器已实现但未做端到端验证（无公开直链镜像）。
- Effect parser 为确定性规则解析器，仅覆盖高频措辞，未覆盖全部裁定细节。
- 未解析出的字段一律标记为 `UNKNOWN`，**不会**被当作「卡片没有该效果」。
- 语义检索未提供真实 embedding 模型时，使用确定性 fallback，仅用于接口验证。
