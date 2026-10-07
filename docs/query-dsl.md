# 查询 DSL（Query DSL）

自然语言永远不直接变成 SQL。它先变成 **Query AST**，再由某个检索后端把 AST 编译成自己需要的形式（SQL、FTS5 MATCH、向量查询）。这样 planner 就与存储解耦了。

AST 是纯 JSON：可序列化、可 diff，也能直接当测试 fixture 用。

---

## 顶层结构

```json
{
  "select": "card",
  "limit": 50,
  "offset": 0,
  "min_confidence": 0.0,
  "where": { ...条件... }
}
```

| 键 | 类型 | 说明 |
| --- | --- | --- |
| `select` | string | 目前只支持 `"card"` |
| `limit` / `offset` | int | 分页 |
| `min_confidence` | float | 预留，用于过滤解析置信度过低的谓词 |
| `where` | 条件 \| 省略 | 省略表示匹配全部 |

---

## 条件

三种节点类型，可自由嵌套。

### 字段条件

```json
{ "field": "card.race", "op": "eq", "value": "DRAGON" }
```

| 运算符 | 含义 |
| --- | --- |
| `eq` / `ne` | 等于 / 不等于。`ne` 同时匹配 UNKNOWN（NULL）。 |
| `in` / `nin` | value 必须是非空列表。`nin` 同时匹配 UNKNOWN。 |
| `lt` `lte` `gt` `gte` | 数值比较 |
| `contains` | 大小写无关的子串匹配（仅限文本字段） |

### 布尔条件

```json
{ "and": [ ... ] }
{ "or":  [ ... ] }
{ "not": { ... } }
```

`and` / `or` 接收非空列表；`not` 接收单个条件。

### 存在条件

```json
{
  "exists": "effect",
  "where": { "and": [ ...谓词条件... ] }
}
```

含义是：*这张卡至少有一条效果，其谓词满足上述条件*。这是把 effect 级约束与 card 级约束组合起来的方式，也是把 COST 与 RESOLUTION 区分开的方式。

---

## 字段

字段名会对照注册表（`query/fields.py`）校验。未知字段名一律拒绝——**没有任何字符串会被拼进 SQL**。

### `card.*`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `card.card_id` | int | |
| `card.canonical_name` | text | |
| `card.card_category` | enum | `MONSTER` `SPELL` `TRAP` |
| `card.sub_category` | enum | `NORMAL` `EFFECT` `FUSION` `RITUAL` `SYNCHRO` `XYZ` `LINK` `PENDULUM` `QUICK_PLAY` `CONTINUOUS` `EQUIP` `FIELD` `COUNTER` `TRAP_MONSTER` `TOKEN` `SKILL` `MAXIMUM` `ARMOR` |
| `card.race` | enum | `DRAGON` `SPELLCASTER` ……（大写下划线） |
| `card.attribute` | enum | `EARTH` `WATER` `FIRE` `WIND` `LIGHT` `DARK` `DIVINE` |
| `card.level_rank` | int | 等级；XYZ 为 rank |
| `card.link_rating` | int | |
| `card.pendulum_scale` | int | |
| `card.atk` / `card.def` | int | `-1` 表示卡面印着 `?` |
| `card.archetype` | text | 关联表，按归一化 slug 匹配 |
| `card.flag` | enum | `TUNER` `PENDULUM` `TOON` `SPIRIT` `UNION` `GEMINI` `FLIP` `TRAP_MONSTER` `ARMOR` `MAXIMUM` |
| `card.name` | text | 任意名称 / 别名行；`contains` 走 LIKE |

### `effect.*`（必须位于 `exists` 块内）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `effect.part` | enum | `CONDITION` `COST` `RESOLUTION` `RESTRICTION` |
| `effect.action` | enum | 见下方词表 |
| `effect.source_zone` | enum | `DECK` `EXTRA_DECK` `HAND` `GRAVEYARD` `BANISHED` `FIELD` `MONSTER_ZONE` `SPELL_TRAP_ZONE` `PENDULUM_ZONE` `ANYWHERE` |
| `effect.destination_zone` | enum | 同一套词表 |
| `effect.target_race` | enum | |
| `effect.target_attribute` | enum | |
| `effect.target_card_category` | enum | `MONSTER` `SPELL` `TRAP` `SPELL_TRAP` |
| `effect.target_archetype` / `effect.target_name` | text | |
| `effect.target_level` | int（虚拟） | 仅支持比较运算 |
| `effect.target_atk` | int（虚拟） | 仅支持比较运算 |
| `effect.target_rank` / `effect.target_link_rating` / `effect.target_count` | int | |
| `effect.target_tuner` | 三值 | `TRUE` `FALSE` `UNKNOWN` |
| `effect.once_per_turn` | 三值 | `TRUE` `FALSE` `UNKNOWN` |
| `effect.confidence` | number | parser 置信度 |

**虚拟区间字段。**「4 星以下」存成 `target_level_max = 4`；精确的「4 星」存成 `min = max = 4`。因此 `effect.target_level` 配 `lte` 会编译成 `(min <= ? OR max <= ?)`，两种写法都能命中。这类字段只支持比较运算符。

**`SPELL_TRAP` 的不对称。** 存成 `SPELL_TRAP` 的谓词（"Target 1 Spell/Trap"）会被查 `SPELL` 或查 `TRAP` 的请求命中；但反过来，查 `SPELL_TRAP` 只匹配那个合并标记本身。

**Action 词表：** `SPECIAL_SUMMON` `NORMAL_SUMMON` `TRIBUTE_SUMMON`
`ADD_TO_HAND` `SEARCH` `DRAW` `SEND_TO_GRAVEYARD` `BANISH` `DESTROY` `NEGATE`
`RETURN_TO_HAND` `RETURN_TO_DECK` `TRIBUTE` `DISCARD` `MILL` `CHANGE_POSITION`
`INCREASE_ATK` `DECREASE_ATK` `EXCAVATE` `REVEAL` `ATTACH` `DETACH`
`GAIN_CONTROL` `COPY_EFFECT` `EQUIP` `SET_CARD` `PREVENT_DESTRUCTION`
`PREVENT_ACTIVATION` `CHANGE_NAME` `SHUFFLE`

---

## 示例

### 4 星以下暗属性恶魔族怪兽

```json
{
  "select": "card",
  "limit": 50,
  "where": {
    "and": [
      { "field": "card.race", "op": "eq", "value": "FIEND" },
      { "field": "card.attribute", "op": "eq", "value": "DARK" },
      { "field": "card.level_rank", "op": "lte", "value": 4 }
    ]
  }
}
```

### 从额外卡组特殊召唤龙族怪兽

```json
{
  "where": {
    "exists": "effect",
    "where": {
      "and": [
        { "field": "effect.part", "op": "eq", "value": "RESOLUTION" },
        { "field": "effect.action", "op": "eq", "value": "SPECIAL_SUMMON" },
        { "field": "effect.source_zone", "op": "eq", "value": "EXTRA_DECK" },
        { "field": "effect.target_race", "op": "eq", "value": "DRAGON" }
      ]
    }
  }
}
```

### 以「除外墓地怪兽」为 COST 并特殊召唤

```json
{
  "where": {
    "and": [
      {
        "exists": "effect",
        "where": {
          "and": [
            { "field": "effect.part", "op": "eq", "value": "COST" },
            { "field": "effect.action", "op": "eq", "value": "BANISH" },
            { "field": "effect.source_zone", "op": "eq", "value": "GRAVEYARD" }
          ]
        }
      },
      {
        "exists": "effect",
        "where": { "field": "effect.action", "op": "eq", "value": "SPECIAL_SUMMON" }
      }
    ]
  }
}
```

### 既不是龙族也不是魔法师族

```json
{ "where": { "not": { "or": [
  { "field": "card.race", "op": "eq", "value": "DRAGON" },
  { "field": "card.race", "op": "eq", "value": "SPELLCASTER" }
] } } }
```

---

## CLI 用法

```bash
# 紧凑过滤语法（裸字段名默认属于 card.*，effect.* 会自动包成 exists 块）
python -m ygolookup.cli search --filter race=DRAGON --filter "level<=4"
python -m ygolookup.cli search --filter effect.action=SPECIAL_SUMMON \
                               --filter effect.source_zone=EXTRA_DECK

# 规则式自然语言 planner
python -m ygolookup.cli search --nl "找能够从额外卡组特殊召唤龙族怪兽的卡"

# 从文件读入完整 AST
python -m ygolookup.cli search --query-file query.json --explain
```

紧凑语法里的别名：`level` / `rank` → `card.level_rank`，`type` → `card.card_category`，
`effect.race` → `effect.target_race`，`effect.level` → `effect.target_level`。

---

## Planner

`query/planner.py` 是 LLM planner 的**确定性占位实现**。它识别一份固定的中英文词表（种族、属性、action、区域），返回 `{query, matched, unmatched}`。

`unmatched` 很重要：当 planner 无法映射问题中的某一部分时，调用方应当回退到 FTS 或语义检索，而不是悄悄把这段意图丢掉。后续阶段的 LLM planner 返回的是同一个 `Query` 对象，因此下游不需要任何改动。
