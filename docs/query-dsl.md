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

### `clause.*` / `effect.*`（必须位于 `exists` 块内）

一个 `exists: effect` 块会编译成 unit → clause → predicate 三层嵌套 `EXISTS`；
块内可以混用 `clause.*` 和 `effect.*`。

| 字段 | 落在哪一层 | 类型 | 说明 |
| --- | --- | --- | --- |
| `clause.role` | clause | enum | `CONDITION` `COST` `TARGET` `RESOLUTION` `RESTRICTION` `UNKNOWN` |
| `clause.once_per_turn` | clause | 三值 | `TRUE` `FALSE` `UNKNOWN` |
| `clause.confidence` | clause | number | |
| `effect.action` | predicate | enum | 见下方词表；**`action_known = 0` 是 UNKNOWN，不是 FALSE** |
| `effect.action_known` | predicate | 0 / 1 | |
| `effect.subject` | predicate | enum | `SELF` `OPPONENT` `PLAYER` `ANY` `UNKNOWN` |
| `effect.source_zone` / `effect.destination_zone` | predicate | enum | `DECK` `EXTRA_DECK` `HAND` `GRAVEYARD` `BANISHED` `FIELD` `MONSTER_ZONE` `SPELL_TRAP_ZONE` `PENDULUM_ZONE` `FIELD_ZONE` `ANYWHERE` |
| `effect.object_race` | predicate | enum | |
| `effect.object_attribute` | predicate | enum | |
| `effect.object_card_type` | predicate | enum | `MONSTER` `SPELL` `TRAP` `SPELL_TRAP` |
| `effect.object_archetype` / `effect.object_name` | predicate | text | |
| `effect.object_count` | predicate | int | |
| `effect.object_level` | predicate | int（虚拟） | 仅支持比较运算 |
| `effect.object_atk` / `effect.object_defense` | predicate | int（虚拟） | 仅支持比较运算 |
| `effect.object_rank` / `effect.object_link_rating` | predicate | int（虚拟） | 仅支持比较运算 |
| `effect.result_ref` / `effect.object_ref` | predicate | text | 简单指代关系 |
| `effect.extracted_by` | predicate | enum | `rule` `grammar` `llm` |
| `effect.confidence` | predicate | number | |

**虚拟区间字段。** 卡面写的是结构化比较「4星以下」→ `{op: "<=", value: 4}`；
精确的「4星」→ `{op: "==", value: 4}`。查询时做区间求交，并且**偏召回**：
卡上 `<= 9` 会被问 `<= 4` 的请求命中，`= 3` 也会，但 `>= 8` 不会。
这类字段只支持 `lt` / `lte` / `gt` / `gte`。

**`SPELL_TRAP` 的不对称。** 存成 `SPELL_TRAP` 的谓词（「以场上1张魔法·陷阱卡为对象」）
会被查 `SPELL` 或查 `TRAP` 的请求命中；但反过来，查 `SPELL_TRAP` 只匹配那个
合并标记本身。

**Action 词表：** `SPECIAL_SUMMON` `NORMAL_SUMMON` `TRIBUTE_SUMMON`
`FUSION_SUMMON` `RITUAL_SUMMON` `SYNCHRO_SUMMON` `XYZ_SUMMON` `LINK_SUMMON`
`ADD_TO_HAND` `SEARCH` `DRAW` `SEND_TO_GRAVEYARD` `MILL` `BANISH` `DESTROY`
`NEGATE` `NEGATE_ACTIVATION` `NEGATE_EFFECTS` `RETURN_TO_HAND` `RETURN_TO_DECK`
`RETURN_TO_EXTRA_DECK` `TRIBUTE` `DISCARD` `DETACH` `REVEAL` `EXCAVATE`
`SHUFFLE` `SET_CARD` `EQUIP` `GAIN_CONTROL` `COPY_EFFECT`
`CHANGE_POSITION` `CHANGE_NAME` `CHANGE_ATTRIBUTE` `CHANGE_RACE`
`CHANGE_LEVEL` `CHANGE_SCALE`
`INCREASE_ATK` `DECREASE_ATK` `INCREASE_DEF` `DECREASE_DEF`
`PAY_LP` `ATTACK_DIRECTLY` `INFLICT_DAMAGE` `PIERCING_DAMAGE`
`PREVENT_DESTRUCTION` `PREVENT_ACTIVATION` `PREVENT_TARGETING`
`PREVENT_ATTACK` `PREVENT_SUMMON`

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
        { "field": "clause.role", "op": "eq", "value": "RESOLUTION" },
        { "field": "effect.action", "op": "eq", "value": "SPECIAL_SUMMON" },
        { "field": "effect.source_zone", "op": "eq", "value": "EXTRA_DECK" },
        { "field": "effect.object_race", "op": "eq", "value": "DRAGON" }
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
            { "field": "clause.role", "op": "eq", "value": "COST" },
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
`effect.race` → `effect.object_race`，`effect.level` → `effect.object_level`，
`effect.part` → `clause.role`。

**注意：** `clause.*` 和 `effect.*` 都必须位于 `exists` 块内——紧凑语法会自动
把这两个前缀包起来。

---

## Planner

`query/planner.py` 是 LLM planner 的**确定性占位实现**。它识别一份固定的中英文词表（种族、属性、action、区域），返回 `{query, matched, unmatched}`。

`unmatched` 很重要：当 planner 无法映射问题中的某一部分时，调用方应当回退到 FTS 或语义检索，而不是悄悄把这段意图丢掉。后续阶段的 LLM planner 返回的是同一个 `Query` 对象，因此下游不需要任何改动。
