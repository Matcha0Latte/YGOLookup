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

当前库里只有 `en`；中文 / 日文名属于后续数据源扩展，schema 已预留。

## `external_id`

主键 `(source, external_id)`——外部标识符只允许出现在这里。

| `source` | 含义 |
| --- | --- |
| `ygopro_passcode` | YGOPro / EDOPro 使用的 8 位密码 |
| `ygoprodeck_id` | YGOProDeck 数字 id |
| `konami_cid` | 预留，官方 OCG/TCG 卡 id |

## `card_archetype`

主键 `(card_id, archetype)`。

- `archetype`：归一化 slug（`blue-eyes`）
- `archetype_raw`：上游原值。对 `cards.cdb` 来说是 16 位 setcode 的十六进制，因为原始库里没有系列名。

## `card_flag`

主键 `(card_id, flag)`。从 type 位字段解码出的布尔标签：`TUNER` `PENDULUM` `TOON` `SPIRIT` `UNION` `GEMINI` `FLIP` `TRAP_MONSTER` `ARMOR` `MAXIMUM`。查询时不必再做位运算。

## 别名

上游 `alias` 表示同一张卡的异画版本。它存在 `card.alias_passcode` 里，但**绝不自动合并**：合并属于人工整理决策，一个错误的上游值会静默毁掉一张卡。用 `id_mapping.alias_report()` 查看候选。

---

## `effect`

一张卡 -> 多个效果。`raw_text` 永远保留，因此每条结构化结论都能回到原始措辞核验。

| 列 | 说明 |
| --- | --- |
| `effect_id` | PK |
| `card_id` | FK → `card`，`ON DELETE CASCADE` |
| `effect_index` | 卡内顺序；`UNIQUE (card_id, effect_index)` |
| `scope` | `MAIN` \| `PENDULUM` \| `MONSTER` |
| `marker` | splitter 如何判定它：`BLOCK` `BULLET` `LINE` `SENTENCE` `MATERIAL` |
| `raw_text` | 精确的文本切片 |
| `text_sha256` | 去重 / 变更检测 |
| `parser_version` | 生成这些谓词的 parser 版本 |

`marker = MATERIAL` 标记召唤素材行（"2 Level 4 monsters"）。它会被存下来——文本本身属于卡面——但不产出任何谓词，因为素材要求不是效果。

## `effect_predicate`

关于「某条效果的某个组成部分」的一条原子断言。

| 列 | 说明 |
| --- | --- |
| `part` | `CONDITION` \| `COST` \| `RESOLUTION` \| `RESTRICTION` |
| `action` | 取自 `Action` 词表；**NULL 表示 UNKNOWN** |
| `action_known` | 0 = UNKNOWN，1 = 已判定。绝不能从 NULL 推断出 FALSE。 |
| `source_zone` / `destination_zone` | 取自 `Zone` 词表 |
| `target_*` | 反范式化的目标列，纯粹为了走索引做 SQL 过滤 |
| `target_tuner` | `TRUE` / `FALSE` / `UNKNOWN` |
| `once_per_turn` | `TRUE` / `FALSE` / `UNKNOWN` |
| `confidence` | 0–1 启发式分值：这个分句被理解了多少 |
| `evidence` | parser 实际匹配到的文本片段 |
| `payload_json` | 完整结构化对象——它才是真相，各列只是镜像 |

### 三值语义

| 状态 | 含义 | SQL 表示 |
| --- | --- | --- |
| `TRUE` | 明确存在 | `target_tuner = 'TRUE'` |
| `FALSE` | 明确否定（"non-Tuner"） | `target_tuner = 'FALSE'` |
| `UNKNOWN` | parser 没能判定 | `target_tuner = 'UNKNOWN'` / `action IS NULL` |

`UNKNOWN` 永远不能被当成 `FALSE`。解析失败不是对卡片的断言。

### 词表

`Action`：`SPECIAL_SUMMON` `NORMAL_SUMMON` `TRIBUTE_SUMMON` `ADD_TO_HAND`
`SEARCH` `DRAW` `SEND_TO_GRAVEYARD` `BANISH` `DESTROY` `NEGATE`
`RETURN_TO_HAND` `RETURN_TO_DECK` `TRIBUTE` `DISCARD` `MILL`
`CHANGE_POSITION` `INCREASE_ATK` `DECREASE_ATK` `EXCAVATE` `REVEAL` `ATTACH`
`DETACH` `GAIN_CONTROL` `COPY_EFFECT` `EQUIP` `SET_CARD`
`PREVENT_DESTRUCTION` `PREVENT_ACTIVATION` `CHANGE_NAME` `SHUFFLE`

`Zone`：`DECK` `EXTRA_DECK` `HAND` `GRAVEYARD` `BANISHED` `FIELD`
`MONSTER_ZONE` `SPELL_TRAP_ZONE` `PENDULUM_ZONE` `ANYWHERE`

`SEARCH` 是 `ADD_TO_HAND` 的更具体形式：当来源为卡组、目标为手牌时才会产出。

`target_card_category` 可能是 `SPELL_TRAP`，查询翻译会把它展开成 `SPELL OR TRAP`。
