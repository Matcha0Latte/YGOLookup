"""Chinese -> canonical vocabulary.

This module is the **single source of truth** for the mapping between the
simplified-Chinese source language and the English machine protocol.

Rules:

* Nothing here may be duplicated as a literal string inside a parser.
* Order matters: the first matching pattern wins, so longer / more specific
  wording is always declared before the generic one it would otherwise shadow
  ("额外卡组" before "卡组", "回到额外卡组" before "回到卡组").
* A pattern may match a *span*; every extraction carries the span so the result
  can be traced back to the original Chinese wording.
"""

from __future__ import annotations

import re

from .ontology import Action, Zone

# ------------------------------------------------------------------- actions
# (pattern, action) — first match wins.
ACTION_LEXICON: tuple[tuple[re.Pattern[str], Action], ...] = (
    # summoning — specific before generic
    (re.compile(r"特殊召唤"), Action.SPECIAL_SUMMON),
    (re.compile(r"通常召唤"), Action.NORMAL_SUMMON),
    (re.compile(r"上级召唤|解放召唤|祭品召唤"), Action.TRIBUTE_SUMMON),
    (re.compile(r"融合召唤"), Action.FUSION_SUMMON),
    (re.compile(r"仪式召唤"), Action.RITUAL_SUMMON),
    (re.compile(r"同步召唤|同调召唤"), Action.SYNCHRO_SUMMON),
    (re.compile(r"超量召唤|XYZ召唤"), Action.XYZ_SUMMON),
    (re.compile(r"连接召唤|链接召唤"), Action.LINK_SUMMON),
    # moving cards — "回到额外卡组" must precede "回到卡组"
    (re.compile(r"回到额外卡组|返回额外卡组"), Action.RETURN_TO_EXTRA_DECK),
    (re.compile(r"回到卡组|返回卡组|回到牌组"), Action.RETURN_TO_DECK),
    (re.compile(r"回到手卡|回到手牌|返回手卡"), Action.RETURN_TO_HAND),
    (re.compile(r"从自己卡组上面把[^。；]*送去墓地"), Action.MILL),
    (re.compile(r"送去墓地|送去目的"), Action.SEND_TO_GRAVEYARD),
    (re.compile(r"加入手卡|加入手牌|加进手卡"), Action.ADD_TO_HAND),
    (re.compile(r"抽卡|抽\d+张"), Action.DRAW),
    (re.compile(r"除外"), Action.BANISH),
    (re.compile(r"破坏"), Action.DESTROY),
    (re.compile(r"发动无效"), Action.NEGATE_ACTIVATION),
    (re.compile(r"效果无效|无效化"), Action.NEGATE_EFFECTS),
    (re.compile(r"无效"), Action.NEGATE),
    (re.compile(r"丢弃"), Action.DISCARD),
    (re.compile(r"解放"), Action.TRIBUTE),
    (re.compile(r"取除|去除"), Action.DETACH),
    (re.compile(r"支付\d+基本分|支付\d+点|支付基本分"), Action.PAY_LP),
    (re.compile(r"给那只[^。；]*装备|当作装备卡|装备卡使用"), Action.EQUIP),
    (re.compile(r"得到[^。；]*控制权|控制权"), Action.GAIN_CONTROL),
    (re.compile(r"变成守备表示|变成攻击表示|变更表示形式|变成里侧"), Action.CHANGE_POSITION),
    (re.compile(r"攻击力上升"), Action.INCREASE_ATK),
    (re.compile(r"攻击力下降|攻击力降低"), Action.DECREASE_ATK),
    (re.compile(r"守备力上升"), Action.INCREASE_DEF),
    (re.compile(r"守备力下降|守备力降低"), Action.DECREASE_DEF),
    (re.compile(r"卡名当作|卡名变成|卡名视为"), Action.CHANGE_NAME),
    (re.compile(r"属性变成|属性当作|当作[^。；]*属性"), Action.CHANGE_ATTRIBUTE),
    (re.compile(r"种族变成|种族当作"), Action.CHANGE_RACE),
    (re.compile(r"等级变成|星级变成"), Action.CHANGE_LEVEL),
    (re.compile(r"刻度变成|灵摆刻度变成"), Action.CHANGE_SCALE),
    (re.compile(r"直接攻击"), Action.ATTACK_DIRECTLY),
    (re.compile(r"给与[^。；]*伤害|受到[^。；]*伤害|伤害"), Action.INFLICT_DAMAGE),
    (re.compile(r"给与[^。；]*战斗伤害[^。；]*穿透|穿透伤害"), Action.PIERCING_DAMAGE),
    (re.compile(r"洗切|洗回|洗牌"), Action.SHUFFLE),
    (re.compile(r"翻开|给对方观看|相互确认|公开"), Action.REVEAL),
    (re.compile(r"从自己卡组上面翻开|翻开[^。；]*张"), Action.EXCAVATE),
    (re.compile(r"盖放|放置"), Action.SET_CARD),
    (re.compile(r"得到[^。；]*效果|当作[^。；]*效果使用"), Action.COPY_EFFECT),
    # prevention
    (re.compile(r"不会成为效果的对象|不能成为效果的对象"), Action.PREVENT_TARGETING),
    (re.compile(r"不会被[^。；]*破坏|不会被战斗破坏|不会被效果破坏"), Action.PREVENT_DESTRUCTION),
    (re.compile(r"不能把[^。；]*发动|不能发动"), Action.PREVENT_ACTIVATION),
    (re.compile(r"不能攻击宣言|不能攻击"), Action.PREVENT_ATTACK),
    (re.compile(r"不能特殊召唤|不能召唤"), Action.PREVENT_SUMMON),
)

# Actions that are legal to pay as a cost.
COST_ACTIONS = frozenset(
    {
        Action.BANISH,
        Action.DISCARD,
        Action.TRIBUTE,
        Action.SEND_TO_GRAVEYARD,
        Action.MILL,
        Action.DETACH,
        Action.REVEAL,
        Action.SHUFFLE,
        Action.RETURN_TO_HAND,
        Action.RETURN_TO_DECK,
        Action.PAY_LP,
        Action.EXCAVATE,
    }
)

# Where an action sends things when the text does not say so.
ACTION_DEFAULT_DESTINATION: dict[Action, Zone] = {
    Action.SPECIAL_SUMMON: Zone.MONSTER_ZONE,
    Action.NORMAL_SUMMON: Zone.MONSTER_ZONE,
    Action.TRIBUTE_SUMMON: Zone.MONSTER_ZONE,
    Action.FUSION_SUMMON: Zone.MONSTER_ZONE,
    Action.RITUAL_SUMMON: Zone.MONSTER_ZONE,
    Action.SYNCHRO_SUMMON: Zone.MONSTER_ZONE,
    Action.XYZ_SUMMON: Zone.MONSTER_ZONE,
    Action.LINK_SUMMON: Zone.MONSTER_ZONE,
    Action.BANISH: Zone.BANISHED,
    Action.SEND_TO_GRAVEYARD: Zone.GRAVEYARD,
    Action.MILL: Zone.GRAVEYARD,
    Action.DISCARD: Zone.GRAVEYARD,
    Action.TRIBUTE: Zone.GRAVEYARD,
    Action.DRAW: Zone.HAND,
    Action.ADD_TO_HAND: Zone.HAND,
    Action.RETURN_TO_HAND: Zone.HAND,
    Action.RETURN_TO_DECK: Zone.DECK,
    Action.RETURN_TO_EXTRA_DECK: Zone.EXTRA_DECK,
    Action.SET_CARD: Zone.SPELL_TRAP_ZONE,
}

# Where an action takes things from when the text does not say so.
ACTION_DEFAULT_SOURCE: dict[Action, Zone] = {
    Action.MILL: Zone.DECK,
    Action.DRAW: Zone.DECK,
}

# --------------------------------------------------------------------- zones
# "额外卡组" before "卡组" — otherwise "额外卡组" degrades to "卡组".
_ZONE_PATTERNS: tuple[tuple[re.Pattern[str], Zone], ...] = (
    (re.compile(r"额外卡组"), Zone.EXTRA_DECK),
    (re.compile(r"卡组|牌组|卡顶"), Zone.DECK),
    (re.compile(r"手卡|手牌"), Zone.HAND),
    (re.compile(r"墓地|坟场"), Zone.GRAVEYARD),
    (re.compile(r"除外状态|除外区|被除外的|除外了的|除外"), Zone.BANISHED),
    (re.compile(r"怪兽区域"), Zone.MONSTER_ZONE),
    (re.compile(r"魔法与陷阱区域|魔法·陷阱区域|魔法陷阱区域"), Zone.SPELL_TRAP_ZONE),
    (re.compile(r"灵摆区域|P区域"), Zone.PENDULUM_ZONE),
    (re.compile(r"场地区域"), Zone.FIELD_ZONE),
    (re.compile(r"场上"), Zone.FIELD),
)

# A zone introduced by one of these prefixes is the SOURCE.
_SOURCE_PREFIX = re.compile(
    r"(?:从|自己|对方|双方)?\s*(?:的)?\s*(?P<zone>额外卡组|卡组|手卡|手牌|墓地|除外状态|除外区|场上|怪兽区域|魔法与陷阱区域|灵摆区域|场地区域)$"
)
_SOURCE_FROM = re.compile(
    r"从(?:自己|对方|双方)?(?:的)?(?P<zone>额外卡组|卡组|手卡|手牌|墓地|除外状态|除外区|场上|怪兽区域|魔法与陷阱区域|灵摆区域|场地区域)"
)

# A zone introduced by one of these is the DESTINATION.
_DESTINATION_TO = re.compile(
    r"(?:到|回到|返回|加入|送去|送回|盖上|放置到|特殊召唤到)(?:自己|对方|双方)?(?:的)?"
    r"(?P<zone>额外卡组|卡组|手卡|手牌|墓地|除外状态|除外区|场上|怪兽区域|魔法与陷阱区域|灵摆区域|场地区域)"
)

_ZONE_BY_WORD = {
    "额外卡组": Zone.EXTRA_DECK,
    "卡组": Zone.DECK,
    "牌组": Zone.DECK,
    "手卡": Zone.HAND,
    "手牌": Zone.HAND,
    "墓地": Zone.GRAVEYARD,
    "坟场": Zone.GRAVEYARD,
    "除外状态": Zone.BANISHED,
    "除外区": Zone.BANISHED,
    "场上": Zone.FIELD,
    "怪兽区域": Zone.MONSTER_ZONE,
    "魔法与陷阱区域": Zone.SPELL_TRAP_ZONE,
    "灵摆区域": Zone.PENDULUM_ZONE,
    "场地区域": Zone.FIELD_ZONE,
}

# ------------------------------------------------------------ clause grammar
# The activation anchor: everything in front of it is condition/cost/target,
# everything after it is the resolution.
ACTIVATION_ANCHORS: tuple[tuple[re.Pattern[str], bool], ...] = (
    (re.compile(r"才能把这张卡发动"), True),
    (re.compile(r"才能发动"), True),
    (re.compile(r"可以发动"), True),
    (re.compile(r"必定发动"), True),
    (re.compile(r"把这张卡发动"), True),
    (re.compile(r"发动"), True),
)

# "以…为对象" marks the targeting clause.
TARGET_PATTERN = re.compile(r"以(?P<object>.+?)为对象")

# A segment in front of the activation anchor that contains one of these is a
# COST — the player has to do something. Without one it is only a CONDITION.
COST_VERB_PATTERN = re.compile(
    r"除外|丢弃|解放|送去墓地|支付|取除|回到手卡|回到卡组|回到额外卡组|洗切|翻开|把这张卡|"
    r"从自己卡组上面把|舍弃|除外了"
)

# Restriction wording: counted uses, hard "cannot", maintenance costs.
RESTRICTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"这个卡名的?[①②③④⑤⑥]?[和・、，,]?[①②③④⑤⑥]?的效果1回合(?:各能|只能|仅能)使用1次"),
    re.compile(r"这个卡名的效果1回合只能使用1次"),
    re.compile(r"「[^」]+」的效果1回合只能使用1次"),
    re.compile(r"1回合1次"),
    re.compile(r"这张卡不能通常召唤"),
    re.compile(r"不能通常召唤"),
    re.compile(r"只能有1只表侧表示存在"),
    re.compile(r"在规则上当作"),
)

# Condition wording: a state or a timing, never something you pay.
CONDITION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"存在的场合"),
    re.compile(r"的场合"),
    re.compile(r".+?时[，,]"),
    re.compile(r"自己(?:主要|准备|结束|战斗|抽卡)阶段"),
    re.compile(r"对方回合"),
    re.compile(r"自己回合"),
    re.compile(r"回合(?:内|中)"),
    re.compile(r"这张卡(?:召唤|特殊召唤|反转|上级召唤|融合召唤|同步召唤|超量召唤|连接召唤)成功"),
    re.compile(r"场上没有怪兽存在"),
    re.compile(r"自己场上有"),
    re.compile(r"只要这张卡"),
)

# ------------------------------------------------------------- measurements
_COUNT_PATTERN = re.compile(r"(\d+)\s*(只|张|个|枚)")
_COUNT_ALL = re.compile(r"(全部|双方|所有)")
_UP_TO = re.compile(r"最多(\d+)\s*(只|张|个|枚)")

_LEVEL_RANGE = re.compile(r"(\d+)星以下|等级(\d+)以下|(\d+)星以下的|Lv\.?(\d+)以下")
_LEVEL_EXACT = re.compile(r"等级(\d+)|(\d+)星|Lv\.?(\d+)")
_LEVEL_MIN = re.compile(r"(\d+)星以上|等级(\d+)以上")

_RANK = re.compile(r"阶级(\d+)|(\d+)阶")
_LINK = re.compile(r"连接(\d+)|LINK-?(\d+)")

_ATK_RANGE = re.compile(r"攻击力(\d+)以下|攻击力(\d+)以上")
_ATK_EXACT = re.compile(r"攻击力(\d+)")
_DEF_RANGE = re.compile(r"守备力(\d+)以下|守备力(\d+)以上")
_DEF_EXACT = re.compile(r"守备力(\d+)")

# Quoted card names — 「…」. Never let their contents feed race/attribute
# detection ("青眼白龙" is a name, not a Dragon).
QUOTED_NAME = re.compile(r"「([^」]{1,60})」")

# Negation sitting immediately in front of an action. "这张卡不能通常召唤" must
# NOT become a NORMAL_SUMMON predicate — that would invert the meaning.
NEGATION_BEFORE = re.compile(r"(?:不能|不会|无法|不得|不必|不可|未能|不受|无效)\s*$")
# Up to six characters may sit between the negation and the verb:
# "不会被那次战斗破坏".
NEGATION_WINDOW = re.compile(r"(不能|不会|无法|不得|不可|未能|不受)[^。；，,]{0,6}$")

# Summoning-material lines are not effects.
MATERIAL_PATTERN = re.compile(
    r"^\s*(?:「[^」]+」\s*[＋+]\s*)?「?[^」]+?」?\s*[＋+]\s*「[^」]+」\s*$"
)
MATERIAL_SIMPLE = re.compile(r"^\s*(?:\d+只以上)?(?:等级|阶级|连接)?\s*\d*[+\s]*.*(?:怪兽|衍生物)\s*$")

# Numbered effect markers.
NUMBER_MARKERS = "①②③④⑤⑥⑦⑧⑨⑩"
NUMBER_MARKER_PATTERN = re.compile(rf"^\s*([{NUMBER_MARKERS}])\s*[：:]\s*")


# ------------------------------------------------------------------ helpers
def find_actions(text: str) -> list[tuple[Action, int, int, str]]:
    """All actions mentioned in `text`, as (action, start, end, matched_text)."""
    out: list[tuple[Action, int, int, str]] = []
    claimed: list[tuple[int, int]] = []
    for pattern, action in ACTION_LEXICON:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < e and s < end for s, e in claimed):
                continue
            claimed.append((start, end))
            out.append((action, start, end, match.group(0)))
    out.sort(key=lambda item: item[1])
    return out


def detect_zones(text: str) -> list[tuple[Zone, int, int, str]]:
    out: list[tuple[Zone, int, int, str]] = []
    claimed: list[tuple[int, int]] = []
    for pattern, zone in _ZONE_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < e and s < end for s, e in claimed):
                continue
            claimed.append((start, end))
            out.append((zone, start, end, match.group(0)))
    out.sort(key=lambda item: item[1])
    return out


def detect_source_zone(text: str) -> Zone | None:
    match = _SOURCE_FROM.search(text)
    if match:
        return _ZONE_BY_WORD.get(match.group("zone"))
    # "自己墓地的1只怪兽" / "对方场上的卡"
    match = re.search(
        r"(?:自己|对方|双方)?(?:的)?(额外卡组|卡组|手卡|手牌|墓地|除外状态|除外区|场上|怪兽区域|魔法与陷阱区域|灵摆区域|场地区域)的",
        text,
    )
    if match:
        return _ZONE_BY_WORD.get(match.group(1))
    return None


def detect_destination_zone(text: str, action: Action | None = None) -> Zone | None:
    match = _DESTINATION_TO.search(text)
    if match:
        return _ZONE_BY_WORD.get(match.group("zone"))
    if action is not None:
        return ACTION_DEFAULT_DESTINATION.get(action)
    return None


def mask_quoted(text: str, replacement: str = "◆") -> str:
    """Replace 「…」 contents with a placeholder.

    Card names routinely contain race and attribute words ("青眼白龙",
    "暗黑界"). Without masking, every one of them becomes a false positive.
    """
    return QUOTED_NAME.sub(lambda m: f"「{replacement * len(m.group(1))}」", text)


def extract_quoted_names(text: str) -> list[str]:
    return [m.group(1).strip() for m in QUOTED_NAME.finditer(text)]


def is_restriction(text: str) -> bool:
    return any(p.search(text) for p in RESTRICTION_PATTERNS)


def has_cost_verb(text: str) -> bool:
    return COST_VERB_PATTERN.search(text) is not None


def looks_like_condition(text: str) -> bool:
    return any(p.search(text) for p in CONDITION_PATTERNS)


def is_negated(text: str, action_start: int, window: int = 12) -> bool:
    """Whether an action at `action_start` is negated by what precedes it.

    "这张卡不能通常召唤" — 通常召唤 starts right after 不能, so the action is
    negated and must not be emitted as a claim.
    """
    head = text[max(0, action_start - window) : action_start]
    if not head:
        return False
    if NEGATION_BEFORE.search(head):
        return True
    return bool(NEGATION_WINDOW.search(head))


def find_activation_anchor(text: str) -> re.Match[str] | None:
    """First activation anchor in the text.

    Only the FIRST one counts: later occurrences are usually "发动无效" or a
    nested clause, and splitting on them destroys the structure.
    """
    for pattern, _ in ACTIVATION_ANCHORS:
        match = pattern.search(text)
        if match:
            return match
    return None
