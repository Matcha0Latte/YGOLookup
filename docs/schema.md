# 数据库 Schema

SQLite 是事实来源。本文是它之上所有层的契约——**任何字段只要没写在这里，其他层就不许假设它存在**。

## 约定

| 约定 | 含义 |
| --- | --- |
| `card_id` | 系统内部自有主键。**永远**不是外部 id。 |
| `NULL` | 对这张卡「不适用」（例如魔法卡的 `race`）。 |
| 哨兵值 `-1` | 上游表示卡面上印着 `?` 的 ATK/DEF。原样保留，绝不转成 0。 |
| `*_mask` | 上游原始位字段，保留下来以便任何导入都能重新推导。 |
| `UNKNOWN` | 专供 effect 层抽取使用（见 [Effect Schema](#effect-schema)），绝不用于 card 字段。 |

## 语言策略

**简体中文是源语言，英文枚举是机器协议。**

- `card_text` 里存的是中文原文；effect 层只读中文，不读英文。
- 落库的值（`Action`、`Zone`、`ClauseRole`、种族、属性……）一律是英文大写枚举，
  由 `effects/lexicon.py` + `effects/ontology.py` 统一映射。这两处是中文词表
  的**唯一**来源，parser 里不允许再出现中文字面量。
- 展示层要中文时，从枚举反查词表，而不是绕过枚举去存中文。

理由：中文词表集中在一处才好维护，检索、过滤、去重都跑在稳定枚举上。

---

## `raw_source`

每次上游快照一行，让任何一次导入都能离线复现。

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `source_id` | INTEGER PK | |
| `source_name` | TEXT | `ygopro_cdb` \| `ygoprodeck_json` |
| `source_version` | TEXT | dump 日期或文件 mtime |
| `uri` / `file_path` | TEXT | 数据来源位置 |
| `content_sha256` | TEXT | 本地 cdb 导入时为 NULL |
| `payload_bytes` / `record_count` | INTEGER | |
| `fetched_at` | TEXT | 本地时间 ISO-8601 |

`UNIQUE (source_name, content_sha256)` 使得重复导入同一份 payload 在 source 层就是空操作。

## `raw_card_record`

逐字节保留的上游记录，每卡每源一行。

| 列 | 说明 |
| --- | --- |
| `raw_id` | PK |
| `source_id` | FK → `raw_source` |
| `card_id` | FK → `card`，upsert 之后回填 |
| `external_id` | 上游 id，便于排查 |
| `payload_sha256` / `payload_json` | 归一化记录的 JSON |

这张表是「不联网也能重新解析」的前提。

## `card`

| 列 | 说明 |
| --- | --- |
| `card_id` | 内部 PK |
| `canonical_name` | 主语言的展示名 |
| `card_category` | `MONSTER` \| `SPELL` \| `TRAP` |
| `sub_category` | `NORMAL` `EFFECT` `FUSION` `RITUAL` `SYNCHRO` `XYZ` `LINK` `PENDULUM` `QUICK_PLAY` `CONTINUOUS` `EQUIP` `FIELD` `COUNTER` `TRAP_MONSTER` `TOKEN` `SKILL` `MAXIMUM` `ARMOR` |
| `race` | `DRAGON`、`WINGED_BEAST`、`SEA_SERPENT` …… 非怪兽为 NULL |
| `attribute` | `EARTH` `WATER` `FIRE` `WIND` `LIGHT` `DARK` `DIVINE` |
| `level_rank` | 等级；XYZ 怪物存的是 rank |
| `link_rating` | 连接值；非 LINK 为 NULL |
| `pendulum_scale` | 灵摆刻度；非 PENDULUM 为 NULL |
| `atk` / `def` | 上游原值，`-1` == `?` |
| `type_mask` 等 | 上游位字段，原样保留 |
| `alias_passcode` | 上游 `alias`；**不会**自动合并（见下文「别名」一节） |
| `text_lang` / `raw_text` | 原始效果文本——永远保留，绝不被派生数据覆盖 |
| `primary_source_id` | FK → `raw_source` |
| `created_at` / `updated_at` | 本地时间 ISO-8601 |

## `card_name`

主键 `(card_id, lang, name_kind, name)`。

- `name_kind`：`official` \| `localized` \| `alias`
- `is_primary`：1 表示这张卡被用作 `canonical_name` 的那个名字

`name_kind` 的判定跟着数据源走：

| `name_kind` | 来源 |
| --- | --- |
| `official` | 官方简体中文名（ygocdb `sc_name`） |
| `localized` | 游戏内译名（ygocdb `md_name`） |
| `alias` | 社区译名（`cn_name` / `nwbbs_n` / `cnocg_n`） |

## `card_text`

主键 `(card_id, lang, kind, source)`。卡面文本按语言和用途分开存，
**与 `card.raw_text` 互不覆盖**——`raw_text` 永远是导入时的原文。

| 列 | 说明 |
| --- | --- |
| `card_id` | FK → `card` |
| `lang` | `zh` \| `en` \| `ja` |
| `kind` | `effect` \| `pendulum` \| `types` |
| `source` | 写入这份文本的数据源（`ygocdb` / `test_fixture` …） |
| `text` | 文本本体 |
| `text_sha256` | 变更检测 |
| `updated_at` | 本地时间 ISO-8601 |

effect 层只读 `lang='zh'` 的行。中文缺失时该卡不产出任何效果——
而不是退回英文去猜。

## `external_id`

主键 `(source, external_id)`——外部标识符只允许出现在这里。

| `source` | 含义 |
| --- | --- |
| `ygopro_passcode` | YGOPro / EDOPro 使用的 8 位密码 |
| `ygoprodeck_id` | YGOProDeck 数字 id |
| `konami_cid` | ygocdb `cid`，用于对齐官方卡表 |

## `card_archetype`

主键 `(card_id, archetype)`。

- `archetype`：归一化 slug（`blue-eyes`）
- `archetype_raw`：上游原值。对 `cards.cdb` 来说是 16 位 setcode 的十六进制，因为原始库里没有系列名。

## `card_flag`

主键 `(card_id, flag)`。从 type 位字段解码出的布尔标签：`TUNER` `PENDULUM` `TOON` `SPIRIT` `UNION` `GEMINI` `FLIP` `TRAP_MONSTER` `ARMOR` `MAXIMUM`。查询时不必再做位运算。

## 别名

上游 `alias` 表示同一张卡的异画版本。它存在 `card.alias_passcode` 里，但**绝不自动合并**：合并属于人工整理决策，一个错误的上游值会静默毁掉一张卡。用 `id_mapping.alias_report()` 查看候选。

---

## Effect Schema（三级模型）

效果层是三张表：

```
effect_unit  一张卡的一段独立文本（① / ② / 卡名限制 / 素材行）
   └── effect_clause   这一段里按角色切出的分句（条件 / cost / 对象 / 处理 …）
          └── effect_predicate   一个分句里的一个原子动作
```

为什么要三层：

- 「COST 是除外、处理是特殊召唤」是两个不同的断言，压平成一列 `part` 表达不了；
- 「以…为对象」的对象约束必须能被单独查询（TARGET 子句）；
- 每条断言都要能追回中文原文和偏移量。

### `effect_unit`

| 列 | 说明 |
| --- | --- |
| `unit_id` | PK |
| `card_id` | FK → `card`，`ON DELETE CASCADE`；`UNIQUE (card_id, unit_index)` |
| `unit_index` | 卡内顺序 |
| `scope` | `MAIN` \| `PENDULUM` \| `MONSTER` |
| `kind` | `NUMBERED` \| `UNNUMBERED` \| `MATERIAL` \| `RESTRICTION` |
| `marker` | `①` `②` …；无编号为 NULL |
| `sub_index` | `●` 列表内的序号 |
| `raw_text` | 精确的文本切片 |
| `text_sha256` | 去重 / 变更检测 |
| `lang` | 源语言，当前恒为 `zh` |
| `parse_status` | `OK` \| `PARTIAL` \| `UNRESOLVED` |
| `parser_version` | 生成这些谓词的 parser 版本（`zh-rule-1`） |
| `parsed_at` | 本地时间 ISO-8601 |

`kind` 的判定：

| `kind` | 何时 |
| --- | --- |
| `NUMBERED` | 以 `①：` 起头的效果 |
| `UNNUMBERED` | 整张卡只有一段效果、没有编号 |
| `RESTRICTION` | 「这个卡名的效果1回合只能使用1次」「这张卡不能通常召唤」这类卡级限制 |
| `MATERIAL` | 召唤素材行——属于卡面，但不是效果，不产出谓词 |

### `effect_clause`

| 列 | 说明 |
| --- | --- |
| `clause_id` | PK |
| `unit_id` | FK → `effect_unit`；`UNIQUE (unit_id, clause_index)` |
| `role` | `CONDITION` \| `COST` \| `TARGET` \| `RESOLUTION` \| `RESTRICTION` \| `UNKNOWN` |
| `raw_text` | 分句文本 |
| `start_offset` / `end_offset` | 在 `unit.raw_text` 中的跨度 |
| `once_per_turn` | `TRUE` / `FALSE` / `UNKNOWN` |
| `confidence` / `extracted_by` | 见下文「解析元数据」 |

切分锚点是**发动**：「发动」之前是条件 / cost / 对象，之后是处理。
但「才能发动」本身不足以判定 COST——「自己场上没有怪兽存在的场合才能发动」
是 CONDITION。判定顺序是 RESTRICTION → TARGET → COST（含可支付动作）→
CONDITION → UNKNOWN。

### `effect_predicate`

| 列 | 说明 |
| --- | --- |
| `predicate_id` | PK |
| `clause_id` | FK → `effect_clause`；`UNIQUE (clause_id, pred_index)` |
| `subject` | `SELF` \| `OPPONENT` \| `PLAYER` \| `ANY` \| `UNKNOWN` |
| `action` | 取自 `Action` 词表；**NULL 表示 UNKNOWN** |
| `action_known` | 0 = UNKNOWN，1 = 已判定。绝不能从 NULL 推断出 FALSE。 |
| `source_zone` / `destination_zone` | 取自 `Zone` 词表 |
| `object_*` | 反范式化的对象列，纯粹为了走索引做 SQL 过滤 |
| `object_level_op` / `object_level_value` 等 | 结构化数值比较，见下文 |
| `result_ref` / `object_ref` | 简单指代关系（同一 unit 内的 `ref_N`） |
| `modifiers_json` | 附加语义，例如 `{"negated_action": "NORMAL_SUMMON"}` |
| `confidence` / `extracted_by` / `source_text` | 解析元数据 |
| `payload_json` | 完整结构化对象——它才是真相，各列只是镜像 |

一个分句可以有多个谓词：「自己从卡组抽1张卡，那之后自己墓地的1只怪兽除外」
产出 `DRAW` 和 `BANISH` 两条。

### 数值比较是结构化的

没有 `max_level` / `min_atk` 这类字段。`CardSelector` 存的是
`{"op": "<=", "value": 4}`，落库时拆成 `object_level_op` + `object_level_value`。

查询翻译会做区间求交，并且**偏召回**：卡上写「4星以下」、用户问「能拉3星吗」
（`<= 3`）要命中；反过来卡上写「9星以下」也命中「4星以下」。

### 三值语义

| 状态 | 含义 | SQL 表示 |
| --- | --- | --- |
| `TRUE` | 明确存在 | `once_per_turn = 'TRUE'` / `action_known = 1` |
| `FALSE` | 明确否定（"non-Tuner"） | `once_per_turn = 'FALSE'` |
| `UNKNOWN` | parser 没能判定 | `once_per_turn = 'UNKNOWN'` / `action IS NULL` |

`UNKNOWN` 永远不能被当成 `FALSE`。解析失败不是对卡片的断言。

`parse_status` 是 unit 级的三态：`OK` 全部判定、`PARTIAL` 部分判定、
`UNRESOLVED` 一条都没判定。只有 `RESOLUTION` / `COST` / `UNKNOWN` 角色的分句
「欠」一个动作——`CONDITION` / `TARGET` 描述的是状态或对象，没有动作也成立；
被否定的动作（「不能通常召唤」）算已判定，不算失败。

### 解析元数据

每条 clause 和 predicate 都带：

| 字段 | 说明 |
| --- | --- |
| `parser_version` | 哪一版 parser 产出的（unit 级） |
| `parse_status` | `OK` / `PARTIAL` / `UNRESOLVED`（unit 级） |
| `confidence` | 0–1 启发式分值 |
| `extracted_by` | `rule` \| `grammar` \| `llm` |
| `source_text` | parser 实际匹配到的中文片段 |
| `source_span` / `start_offset` / `end_offset` | 在原文中的位置 |

LLM 产出的结果一律标 `extracted_by = 'llm'`，与规则产出分开统计。
**v1 的 LLM 抽取层是空实现**（`LlmExtractor.extract()` 返回 `None`），
只把接口和标注位置留好。

### 词表

`Action`：`SPECIAL_SUMMON` `NORMAL_SUMMON` `TRIBUTE_SUMMON` `FUSION_SUMMON`
`RITUAL_SUMMON` `SYNCHRO_SUMMON` `XYZ_SUMMON` `LINK_SUMMON` `ADD_TO_HAND`
`SEARCH` `DRAW` `SEND_TO_GRAVEYARD` `MILL` `BANISH` `DESTROY` `NEGATE`
`NEGATE_ACTIVATION` `NEGATE_EFFECTS` `RETURN_TO_HAND` `RETURN_TO_DECK`
`RETURN_TO_EXTRA_DECK` `TRIBUTE` `DISCARD`
`CHANGE_POSITION` `INCREASE_ATK` `DECREASE_ATK` `INCREASE_DEF` `DECREASE_DEF`
`CHANGE_ATTRIBUTE` `CHANGE_RACE` `CHANGE_LEVEL` `CHANGE_SCALE` `CHANGE_NAME`
`EXCAVATE` `REVEAL` `DETACH` `GAIN_CONTROL` `COPY_EFFECT` `EQUIP` `SET_CARD`
`SHUFFLE` `PAY_LP` `ATTACK_DIRECTLY` `INFLICT_DAMAGE` `PIERCING_DAMAGE`
`PREVENT_DESTRUCTION` `PREVENT_ACTIVATION` `PREVENT_TARGETING`
`PREVENT_ATTACK` `PREVENT_SUMMON`

`Zone`：`DECK` `EXTRA_DECK` `HAND` `GRAVEYARD` `BANISHED` `FIELD`
`MONSTER_ZONE` `SPELL_TRAP_ZONE` `PENDULUM_ZONE` `FIELD_ZONE` `ANYWHERE`

`ClauseRole`：`CONDITION` `COST` `TARGET` `RESOLUTION` `RESTRICTION` `UNKNOWN`

`SEARCH` 是 `ADD_TO_HAND` 的更具体形式：当来源为卡组、目标为手牌时才会产出。

`object_card_type` 可能是 `SPELL_TRAP`，查询翻译会把它展开成 `SPELL OR TRAP`。

v1 **不处理**：连锁速度、伤害步骤、错过时点、代替 / 持续效果、完整召唤手续、
完整裁定。这些留给后续阶段。
