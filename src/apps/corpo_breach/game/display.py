"""Display helpers for the CorpoBreach RPG badge app."""

from displayio import Group
from terminalio import FONT
from adafruit_display_text.label import Label
from adafruit_display_shapes.rect import Rect

from badge.constants import BLACK, WHITE, GREEN, RED, YELLOW, CYAN, BLUE, BB_WIDTH
from badge.screens import clear_screen, center_text_x_plane, wrap_message, round_button
from apps.corpo_breach.game.api import (
    EVENT_ABILITY_NOT_EQUIPPED,
    EVENT_DEFENSIVE_ABILITY_WRONG_TURN,
    EVENT_ITEM_ATTACK_TURN_ONLY,
    EVENT_ITEM_DEFENSE_TURN_ONLY,
    EVENT_ITEM_LOCKOUT,
    EVENT_ITEM_NOT_AVAILABLE,
    EVENT_MOVE_ALREADY_SUBMITTED,
    EVENT_NOT_ENOUGH_RAM,
    EVENT_OFFENSIVE_ABILITY_WRONG_TURN,
    EVENT_SILENCED,
)

DARK_GRAY = 0x333333

SIDES = ("PHYSICAL", "NETWORK", "SOCIAL", "WIRELESS", "SUPPLY")
SIDE_COLORS = {
    "PHYSICAL": RED,
    "NETWORK": YELLOW,
    "SOCIAL": GREEN,
    "WIRELESS": CYAN,
    "SUPPLY": BLUE,
}
SIDE_ABBR = {
    "PHYSICAL": "PHY",
    "NETWORK": "NET",
    "SOCIAL": "SOC",
    "WIRELESS": "WIR",
    "SUPPLY": "SUP",
}


ROUND_RESULT_MAX_LINES = 6

EFFECT_ABBR = {
    "BUFF_ATTACK": "ATK+",
    "BUFF_DEFENSE": "DEF+",
    "BUFF_BALANCED": "BAL+",
    "BUFF_RAM_COST": "RAM+",
    "DEBUFF_ATTACK": "ATK-",
    "DEBUFF_DEFENSE": "DEF-",
    "DEBUFF_RAM_COST": "RAM-",
    "DAMAGE_OVER_TIME": "DOT",
    "DOT": "DOT",
    "SILENCE": "SIL",
    "SIL": "SIL",
    "ITEM_LOCKOUT": "LOCK",
    "LOCK": "LOCK",
    "REFLECT": "REF",
    "REF": "REF",
    "SHIELD": "SHLD",
    "SHLD": "SHLD",
}


def label(text, x=0, y=8, color=WHITE, scale=1):
    return Label(font=FONT, text=str(text), x=x, y=y, color=color, scale=scale)


def show_message(screen, title, body="", color=WHITE):
    clear_screen(screen)
    g = Group()
    g.append(center_text_x_plane(screen, title, y=12, color=color))
    if body:
        msg = wrap_message(screen, body, x=2, y=30)
        msg.color = color
        g.append(msg)
    screen.root_group.append(g)


BUTTON_SLOTS = (("S4", "a"), ("S5", "b"), ("S6", "c"), ("S7", "d"))


def _button_text(slot, action, max_chars):
    if not action:
        return ""
    text = "%s %s" % (slot, action)
    return text[:max_chars]


def _button_width(text):
    lb = label(text)
    return lb.bounding_box[BB_WIDTH] * lb.scale + 10


def button_bar_height(screen):
    return 24 if screen.height >= 120 else 20


def _button_entries(screen, a="", b="", c="", d=""):
    """Return evenly spaced one-line EPD button legend entries."""
    actions = {"a": a, "b": b, "c": c, "d": d}
    # Trim action names until every visible S# action fits on one row.
    max_chars = 11
    while max_chars >= 4:
        entries = []
        total_width = 0
        for slot, key in BUTTON_SLOTS:
            text = _button_text(slot, actions.get(key, ""), max_chars)
            if text:
                width = _button_width(text)
                entries.append([text, width])
                total_width += width
        if not entries:
            return []
        gap = (screen.width - total_width) // (len(entries) + 1)
        if gap >= 2 or max_chars == 4:
            x = max(2, gap)
            y = screen.height - (button_bar_height(screen) // 2)
            positioned = []
            for text, width in entries:
                positioned.append((text, x + 5, y))
                x += width + max(2, gap)
            return positioned
        max_chars -= 1
    return []


def _append_button_legend(g, screen, a="", b="", c="", d=""):
    top = screen.height - button_bar_height(screen)
    g.append(Rect(0, top, screen.width, 1, fill=WHITE))
    for text, x, y in _button_entries(screen, a, b, c, d):
        g.append(round_button(label(text, color=WHITE), x, y, 4, color=WHITE, fill=None))


def draw_button_bar(epd, a="", b="", c="", d=""):
    _render_status_epd(epd, prefix="----", status_lines=["CorpoBreach"], a=a, b=b, c=c, d=d)


_LAST_EPD_SIGNATURE = None


def _effect_signature(effect):
    """Return a compact, comparable signature for an active effect."""
    if isinstance(effect, dict):
        return (
            effect.get("effect_type") or effect.get("type") or effect.get("name"),
            effect.get("rounds_remaining"),
            effect.get("duration_remaining"),
            effect.get("remaining_rounds"),
        )
    return str(effect)


def _status_epd_signature(epd, metrics, prefix, status_lines, a, b, c, d):
    """Return the content key used to skip redundant EPD refreshes."""
    return (
        epd.width,
        epd.height,
        prefix,
        metrics.get("hp_cur"),
        metrics.get("hp_max"),
        metrics.get("ram_cur"),
        metrics.get("ram_max"),
        metrics.get("attack"),
        metrics.get("defense"),
        tuple(_effect_signature(effect) for effect in metrics.get("effects", [])),
        tuple(str(line) for line in (status_lines or ["CorpoBreach"])),
        a,
        b,
        c,
        d,
    )


def reset_epd_signature_cache():
    """Force the next CorpoBreach EPD status render to refresh the panel."""
    global _LAST_EPD_SIGNATURE
    _LAST_EPD_SIGNATURE = None


def stat_value(stats, *names):
    for name in names:
        if name in stats:
            return stats[name]
    return 0


def hp_bar(width, current_hp, max_hp):
    return value_bar(width, current_hp, max_hp)


def value_bar(width, current, maximum, height=10):
    """Two-box EPD status bar with a 1px border and calculated fill."""
    maximum = max(1, _as_int(maximum, 1))
    current = max(0, min(_as_int(current, 0), maximum))
    inner_width = max(1, width - 2)
    filled = int((current / maximum) * inner_width)
    g = Group()
    g.append(Rect(0, 0, width, height, outline=WHITE, fill=None))
    if filled > 0:
        g.append(Rect(1, 1, max(1, filled), max(1, height - 2), fill=WHITE))
    return g


def _stat_total(stats, base_names, effects, buff_key, debuff_key):
    value = stat_value(stats, *base_names)
    for effect in effects:
        key = _effect_text(effect, compact=True)
        amount = 1
        if isinstance(effect, dict):
            amount = _as_int(effect.get("amount", effect.get("value", effect.get("modifier", 1))), 1)
        if key.startswith(buff_key):
            value += amount
        elif key.startswith(debuff_key):
            value -= amount
    return value


def _empty_metrics():
    return {
        "hp_cur": 0,
        "hp_max": 0,
        "ram_cur": 0,
        "ram_max": 0,
        "attack": 0,
        "defense": 0,
        "effects": [],
    }


def _current_max(stats, current_names, max_names):
    current = stat_value(stats, *current_names)
    maximum = stat_value(stats, *max_names)
    if not maximum and current:
        maximum = current
    return current, maximum


def _player_metrics(player_state):
    stats = (player_state or {}).get("stats", {})
    effects = effects_for_player(player_state or {})
    hp_cur, hp_max = _current_max(stats, ("current_hp", "hp", "health", "current_health"),
                                  ("max_hp", "max_health", "health_max"))
    ram_cur, ram_max = _current_max(stats, ("current_ram", "ram", "mana", "current_mana"),
                                    ("max_ram", "max_mana", "mana_max"))
    return {
        "hp_cur": hp_cur,
        "hp_max": hp_max,
        "ram_cur": ram_cur,
        "ram_max": ram_max,
        "attack": _stat_total(stats, ("attack", "base_attack"), effects, "ATK+", "ATK-"),
        "defense": _stat_total(stats, ("defense", "base_defense"), effects, "DEF+", "DEF-"),
        "effects": effects,
    }


def _combat_metrics(game_state):
    return _player_metrics((game_state or {}).get("you", {}))


def _append_separator(g, screen, y):
    g.append(Rect(0, y, screen.width, 1, fill=WHITE))


def _append_resource_bar(g, screen, label_text, current, maximum, x, y, width):
    g.append(label(label_text, x, y + 8, WHITE))
    bar = value_bar(width, current, maximum)
    bar.x = x + 24
    bar.y = y
    g.append(bar)


def _append_combat_bars(g, screen, metrics, top=4, height=20):
    gap = 10
    side_width = (screen.width - gap - 8) // 2
    bar_width = max(32, side_width - 26)
    _append_resource_bar(g, screen, "HP", metrics["hp_cur"], metrics["hp_max"], 4, top + 3, bar_width)
    _append_resource_bar(g, screen, "RAM", metrics["ram_cur"], metrics["ram_max"], 4 + side_width + gap, top + 3, bar_width)
    _append_separator(g, screen, top + height)


def _append_status_stats(g, screen, metrics, prefix, top):
    line = "%s HP:%s/%s RAM:%s/%s ATK:%s DEF:%s" % (
        prefix, metrics["hp_cur"], metrics["hp_max"], metrics["ram_cur"],
        metrics["ram_max"], metrics["attack"], metrics["defense"])
    g.append(label(line[:43], 2, top + 11, WHITE))
    _append_separator(g, screen, top + 20)


def _message_columns(screen, top, bottom, lines):
    available_h = max(12, bottom - top)
    rows = max(1, available_h // 14)
    if len(lines) <= rows:
        return [(2, top + 10 + idx * 14, screen.width - 4, line) for idx, line in enumerate(lines[:rows])]
    left_w = (screen.width // 2) - 4
    positioned = []
    for idx, line in enumerate(lines[:rows * 2]):
        col = idx // rows
        row = idx % rows
        x = 2 if col == 0 else screen.width // 2 + 2
        positioned.append((x, top + 10 + row * 14, left_w, line))
    return positioned


def _append_message_area(g, screen, top, bottom, status_lines):
    lines = status_lines or ["CorpoBreach"]
    for x, y, width, text in _message_columns(screen, top, bottom, [str(line) for line in lines]):
        max_chars = max(8, width // 6)
        g.append(label(text[:max_chars], x, y, WHITE))
    _append_separator(g, screen, bottom)


def _status_layout(screen):
    bars_top = 2
    bars_h = 24
    stats_top = bars_top + bars_h
    stats_h = 20
    buttons_h = button_bar_height(screen)
    return bars_top, bars_h, stats_top, stats_h, stats_top + stats_h, screen.height - buttons_h


def _render_status_epd(epd, metrics=None, prefix="----", status_lines=None, a="", b="", c="", d=""):
    """Render the shared CorpoBreach EPD template for every app state."""
    global _LAST_EPD_SIGNATURE
    if isinstance(status_lines, str):
        status_lines = [status_lines]
    metrics = metrics or _empty_metrics()
    signature = _status_epd_signature(epd, metrics, prefix, status_lines, a, b, c, d)
    if signature == _LAST_EPD_SIGNATURE:
        return

    bars_top, bars_h, stats_top, _stats_h, message_top, message_bottom = _status_layout(epd)
    clear_screen(epd)
    g = Group()
    # Append mostly-static sections first. Message content is last so it can be
    # replaced independently later without rebuilding the controls and status.
    _append_button_legend(g, epd, a, b, c, d)
    _append_combat_bars(g, epd, metrics, bars_top, bars_h)
    _append_status_stats(g, epd, metrics, prefix, stats_top)
    _append_message_area(g, epd, message_top, message_bottom, status_lines)
    epd.root_group.append(g)
    epd.refresh()
    _LAST_EPD_SIGNATURE = signature


def effects_for_player(player_state):
    return player_state.get("active_effects") or player_state.get("effects") or []


def _effect_text(effect, compact=False):
    if isinstance(effect, dict):
        raw = effect.get("effect_type") or effect.get("type") or effect.get("name") or "effect"
        rounds = effect.get("rounds_remaining")
        if rounds is None:
            rounds = effect.get("duration_remaining") or effect.get("remaining_rounds")
    else:
        raw = str(effect)
        rounds = None
    key = str(raw).upper()
    name = EFFECT_ABBR.get(key, key[:4]) if compact else key.replace("_", " ")[:15]
    if rounds is not None:
        return "%s%s" % (name, rounds) if compact else "%s:%s" % (name, rounds)
    return name


def effect_summary(effects, compact=False, max_items=3, max_chars=20):
    if not effects:
        return "none"
    return " ".join(_effect_text(e, compact) for e in effects[:max_items])[:max_chars]


def show_player_status_epd(epd, player_state, a="", b="", c="", d="", prefix="IDLE", status_lines=None):
    metrics = _player_metrics(player_state)
    lines = status_lines or ["CorpoBreach"]
    if metrics["effects"] and status_lines is None:
        lines.append("FX " + effect_summary(metrics["effects"], True, max_chars=28))
    _render_status_epd(epd, metrics, prefix, lines, a, b, c, d)


def _as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def side_value(side):
    return side.get("side") if isinstance(side, dict) else side


def side_index(side):
    if isinstance(side, dict):
        return _as_int(side.get("row_index"), 0)
    key = side_key(side)
    try:
        return SIDES.index(key)
    except ValueError:
        return 0


def side_key(side):
    return str(side_value(side) or "").upper()


def side_color(side):
    return SIDE_COLORS.get(side_key(side), BLACK)


def side_abbr(side):
    return SIDE_ABBR.get(side_key(side), str(side or "?")[:3].upper())


def side_style(side):
    bg = DARK_GRAY if side_index(side) % 2 else BLACK
    return side_color(side), bg


def adjacent_sides(side):
    side = side_key(side)
    if side not in SIDES:
        return None, None
    idx = SIDES.index(side)
    return SIDES[(idx - 1) % len(SIDES)], SIDES[(idx + 1) % len(SIDES)]


def side_prompt(role):
    role = str(role or "").lower()
    if role.startswith("attack"):
        return "Attack vector"
    if role.startswith("defend"):
        return "Defense side"
    return "Combat side"


def ability_value(ability):
    return ability.get("ability") if isinstance(ability, dict) and "ability" in ability else ability


def ability_side(ability):
    ability = ability_value(ability)
    return ability.get("side") or ability.get("pentagon_side") or ability.get("area") or ability.get("attack_area")


def ability_label(ability):
    ability = ability_value(ability)

    side = ability_side(ability)
    text = "%s R%s" % (ability.get("name", "Ability"), ability.get("ram_cost", "?"))
    return (text + " " + str(side)[:3])[:20] if side else text[:20]


def _description_text(row, *names):
    obj = ability_value(row) if isinstance(row, dict) and "ability" in row else row
    if not isinstance(obj, dict):
        return ""
    for name in names:
        value = obj.get(name)
        if value:
            return str(value)
    return ""


def _wrap_text_lines(text, max_chars=28, max_lines=3):
    words = str(text).split()
    lines = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word[:max_chars]
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def ability_description_lines(ability, max_chars=28):
    ability = ability_value(ability)
    side = ability_side(ability)
    kind = ability.get("ability_type") or ability.get("type") or "Special"
    lines = [ability.get("name", "Special")[:max_chars]]
    lines.append(("RAM %s %s %s" % (ability.get("ram_cost", "?"), str(kind)[:3].upper(), side_abbr(side)))[:max_chars])
    text = _description_text(ability, "description", "effect", "effect_description", "short_description")
    if text:
        lines.extend(_wrap_text_lines(text, max_chars, 3))
    return lines[:5]


def _effect_value_text(value):
    if value is None:
        return ""
    try:
        number = float(value)
        if number <= 1:
            number *= 100
        return "%d%%" % int(number)
    except Exception:
        return str(value)[:4]


def ability_mitigation_lines(ability, max_chars=20):
    """Return compact LCD lines explaining an ability's side/tier sets."""
    ability = ability_value(ability)
    if not isinstance(ability, dict):
        return ["No mitigation data"]
    side = ability_side(ability)
    side_key_value = side_key(side)
    if side_key_value not in SIDES:
        return ["No mitigation data"]

    left, right = adjacent_sides(side_key_value)
    other = [entry for entry in SIDES if entry not in (side_key_value, left, right)]
    kind = str(ability.get("ability_type") or ability.get("type") or "").upper()
    offensive = kind.startswith("OFF") or kind.startswith("ATTACK")
    defensive = kind.startswith("DEF") or kind.startswith("DEFEND")
    if not offensive and not defensive:
        return ["No mitigation data"]

    values = {
        "FULL": _effect_value_text(ability.get("effect_value_full")),
        "MED": _effect_value_text(ability.get("effect_value_medium")),
        "LOW": _effect_value_text(ability.get("effect_value_low")),
    }
    if not values["FULL"] and not values["MED"] and not values["LOW"]:
        return ["No mitigation data"]

    same_tier = "LOW" if offensive else "FULL"
    other_tier = "FULL" if offensive else "LOW"
    adjacent_text = "%s/%s" % (side_abbr(left), side_abbr(right))
    other_text = "%s/%s" % (side_abbr(other[0]), side_abbr(other[1]))
    lines = ["Mitigation sets"]
    for prefix, sides, tier in (("Same", side_abbr(side_key_value), same_tier),
                                ("Adj", adjacent_text, "MED"),
                                ("O", other_text, other_tier)):
        value = values.get(tier, "")
        suffix = (" " + value) if value else ""
        lines.append(("%s %s: %s%s" % (prefix, sides, tier, suffix))[:max_chars])
    return lines[:5]


def ability_style(ability, current_ram=0, blocked=False):
    row = ability
    ability = ability_value(ability)
    affordable = _as_int(ability.get("ram_cost"), 0) <= _as_int(current_ram, 0)
    equipped = ability.get("equipped", True)
    fg = DARK_GRAY if blocked or not affordable or not equipped else side_color(ability_side(ability))
    bg = DARK_GRAY if side_index(row) % 2 else BLACK
    return fg, bg


def loadout_label(row):
    ability = row.get("ability", row)
    action = row.get("action", "")[:1].upper()
    kind = (ability.get("ability_type") or ability.get("type") or "")[:1].upper()
    equipped = ability.get("is_equipped", ability.get("equipped", row.get("equipped", True)))
    mark = "*" if equipped else "-"
    name = ability.get("name", "Ability")
    cost = ability.get("ram_cost", ability.get("cost", "?"))
    side = ability_side(ability)
    suffix = "%s%s R%s" % (action or mark, kind, cost)
    text = "%s %s" % (suffix, name)
    if side:
        text += " " + str(side)[:3]
    return text[:20]


def loadout_style(row):
    ability = row.get("ability", row)
    unavailable = row.get("unavailable") or ability.get("unlocked", True) is False
    return (DARK_GRAY if unavailable else WHITE), side_color(ability_side(ability))


def _flag_value(value):
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


def _item_flag(item_row, key):
    item = item_row.get("item", item_row)
    if key in item_row:
        return _flag_value(item_row.get(key))
    return _flag_value(item.get(key))


def item_usage_flags(item_row):
    """Return explicit server item usage flags as (attack, defense, outside)."""
    return (
        _item_flag(item_row, "usable_on_attack_turn"),
        _item_flag(item_row, "usable_on_defense_turn"),
        _item_flag(item_row, "usable_outside_battle"),
    )


def item_usage_label(item_row, include_outside=True):
    attack, defense, outside = item_usage_flags(item_row)
    parts = []
    if attack and defense:
        parts.append("ANY")
    elif attack:
        parts.append("ATK")
    elif defense:
        parts.append("DEF")
    if include_outside and outside:
        parts.append("OOB")
    return "/".join(parts)


def item_label(item_row):
    item = item_row.get("item", item_row)
    name = item.get("name", "Item")
    qty = item_row.get("quantity", item.get("quantity", 1))
    usage = item_usage_label(item_row)
    suffix = " %s" % usage if usage else ""
    return ("%s x%s%s" % (name, qty, suffix))[:20]


def item_description_lines(item_row, max_chars=28):
    item = item_row.get("item", item_row)
    qty = item_row.get("quantity", item.get("quantity", 1))
    usage = item_usage_label(item_row)
    lines = [item.get("name", "Item")[:max_chars]]
    detail = "Qty %s" % qty
    if usage:
        detail = "%s %s" % (detail, usage)
    lines.append(detail[:max_chars])
    text = _description_text(item, "description", "effect", "effect_description", "short_description")
    if text:
        lines.extend(_wrap_text_lines(text, max_chars, 3))
    return lines[:5]


def item_usable(item_row, role=None, blocked=False):
    if blocked:
        return False
    item = item_row.get("item", item_row)
    qty = item_row.get("quantity", item.get("quantity", 1))
    if _as_int(qty, 0) <= 0:
        return False
    attack, defense, outside = item_usage_flags(item_row)
    role = str(role or "").lower()
    if role in ("attacker", "attack"):
        return attack
    if role in ("defender", "defense", "defend"):
        return defense
    return outside


def item_style(item_row, role=None, blocked=False):
    return (WHITE if item_usable(item_row, role, blocked) else DARK_GRAY), BLACK


def show_side_selector(g, screen, top, selected_side, role):
    width = screen.width
    side = side_key(selected_side) or "PHYSICAL"
    left, right = adjacent_sides(side)
    g.append(label(side_prompt(role), 2, top, CYAN))
    g.append(Rect(2, top + 10, width - 4, 24, fill=side_color(side)))
    g.append(center_text_x_plane(screen, side_abbr(side) + " " + side, y=top + 25, color=WHITE))
    if left and right and width >= 96 and top + 58 <= screen.height:
        y = top + 44
        box = max(42, (width - 12) // 2)
        g.append(Rect(2, y - 10, box, 16, fill=side_color(left)))
        g.append(label("<" + side_abbr(left), 5, y, WHITE))
        g.append(Rect(width - box - 2, y - 10, box, 16, fill=side_color(right)))
        g.append(label(side_abbr(right) + ">", width - box + 1, y, WHITE))


def rpg_error_message(payload):
    if payload.get("server_error") or payload.get("http_status", 200) >= 500:
        return "Server error; retry"
    event_id = payload.get("event_id")
    if event_id == EVENT_NOT_ENOUGH_RAM:
        return "Not enough resource"
    if event_id == EVENT_MOVE_ALREADY_SUBMITTED:
        return "Move already sent"
    if event_id == EVENT_SILENCED:
        return "Silenced: no abilities"
    if event_id == EVENT_ITEM_LOCKOUT:
        return "Item locked"
    if event_id in (EVENT_ITEM_ATTACK_TURN_ONLY, EVENT_ITEM_DEFENSE_TURN_ONLY,
                    EVENT_OFFENSIVE_ABILITY_WRONG_TURN, EVENT_DEFENSIVE_ABILITY_WRONG_TURN):
        return "Wrong turn"
    if event_id == EVENT_ABILITY_NOT_EQUIPPED:
        return "Ability not equipped"
    if event_id == EVENT_ITEM_NOT_AVAILABLE:
        return "Item unavailable"
    text = (payload.get("message") or payload.get("error") or payload.get("status") or "Try another move")
    low = str(text).lower()
    if "ram" in low and ("not enough" in low or "insufficient" in low):
        return "Not enough resource"
    if "silence" in low or "silenced" in low:
        return "Silenced: no abilities"
    if "item" in low and ("lock" in low or "locked" in low):
        return "Item locked"
    if "wrong turn" in low or "attack turn" in low or "defense turn" in low:
        return "Item wrong turn"
    if "not equipped" in low or "unequipped" in low:
        return "Ability not equipped"
    if "unavailable" in low or "quantity" in low or "inventory" in low:
        return "Item unavailable"
    if "already" in low or "duplicate" in low or "submitted" in low:
        return "Move already sent"
    return str(text)[:40]


def show_combat_state(lcd, game_state, selected_side=None, selected_move=None):
    opp = game_state.get("opponent", {})
    clear_screen(lcd)
    g = Group()
    g.append(label("R%s %s" % (game_state.get("round", "?"), game_state.get("your_role", "?")), 2, 8, CYAN))
    g.append(label("FOE %s" % opp.get("player_name", "Opponent"), 2, 26))
    if game_state.get("you_submitted"):
        g.append(label("Move submitted", 2, 48, YELLOW))
        g.append(label("Waiting..." if not game_state.get("opponent_submitted") else "Resolving...", 2, 66))
    else:
        side = selected_side or "PHYSICAL"
        g.append(label("Move: %s" % (selected_move or "basic"), 2, 48, YELLOW))
        show_side_selector(g, lcd, 58, side, game_state.get("your_role"))
    lcd.root_group.append(g)


def show_combat_status_epd(epd, game_state, a="", b="", c="", d="", status_lines=None):
    """Render the persistent in-match EPD using the shared template."""
    if isinstance(status_lines, str):
        status_lines = [status_lines]
    metrics = _combat_metrics(game_state)
    prefix = "R%s %s" % (game_state.get("round", "?"), str(game_state.get("your_role", "?"))[:3])
    if metrics["effects"]:
        lines = list(status_lines or [])
        lines.append("FX " + effect_summary(metrics["effects"], True, max_chars=28))
    else:
        lines = status_lines
    _render_status_epd(epd, metrics, prefix, lines, a, b, c, d)


def _role_for_result(game_state, result):
    you_id = game_state.get("you", {}).get("player_id")
    if you_id == result.get("attacker_id"):
        return "attacker"
    if you_id == result.get("defender_id"):
        return "defender"
    return game_state.get("your_role")


def _ability_name_from_log(log_entries, actor):
    """Extract a compact ability name from server round log text."""
    markers = ("%s ability '" % actor, "%s defensive ability '" % actor,
               "%s offensive ability '" % actor)
    for entry in log_entries or []:
        text = str(entry)
        low = text.lower()
        for marker in markers:
            start = low.find(marker)
            if start >= 0:
                start += len(marker)
                end = text.find("'", start)
                if end > start:
                    return text[start:end]
    return None


def _round_log_text(result):
    return " ".join(result.get("log", [])).lower()


def _move_type_for_actor(result, actor, selected_move=None, local_actor=None):
    if selected_move and actor == local_actor:
        return selected_move.get("move_type")
    for key in (actor + "_move_type", actor + "_action", actor + "_move", actor + "_choice"):
        value = result.get(key)
        if isinstance(value, dict):
            value = value.get("move_type") or value.get("type") or value.get("action")
        if value:
            return str(value).lower()
    log_text = _round_log_text(result)
    if "%s used item" % actor in log_text:
        return "item"
    if "%s passed" % actor in log_text or "%s pass" % actor in log_text:
        return "pass"
    if _ability_name_from_log(result.get("log", []), actor):
        return "ability"
    return "basic"


def _choice_token(result, actor, selected_move=None, local_actor=None):
    move_type = _move_type_for_actor(result, actor, selected_move, local_actor) or "basic"
    if move_type.startswith("item"):
        return "ITM"
    if move_type.startswith("pass"):
        return "PAS"
    side = None
    if selected_move and actor == local_actor:
        side = selected_move.get("side")
    if not side:
        side = result.get(actor + "_side")
    return side_abbr(side) if side else "???"


def _mitigation_token(result):
    value = str(result.get("mitigation_result") or result.get("mitigation") or "none").upper()
    if value.startswith("FULL"):
        return "FULL"
    if value.startswith("PART"):
        return "PART"
    if value in ("BASE", "NO", "NONE", "NULL", "0"):
        return "NONE"
    return value[:8]


def _selection_lines(game_state, result, selected_move=None):
    role = _role_for_result(game_state, result)
    local_actor = "attacker" if str(role).startswith("attack") else "defender"
    if local_actor == "attacker":
        matchup = "ATK:%s - DEF:%s" % (
            _choice_token(result, "attacker", selected_move, local_actor),
            _choice_token(result, "defender", selected_move, local_actor),
        )
    else:
        matchup = "DEF:%s - ATK:%s" % (
            _choice_token(result, "defender", selected_move, local_actor),
            _choice_token(result, "attacker", selected_move, local_actor),
        )
    return [matchup, "MIT:%s" % _mitigation_token(result)]


def _append_unique(lines, text):
    if text and text not in lines:
        lines.append(text)


def _actor_field(result, actor, name):
    return stat_value(result, actor + "_" + name, name + "_" + actor)


def _actor_flag(result, actor, name):
    return _flag_value(result.get(actor + "_" + name) or result.get(name + "_" + actor))


def _line_delta(label_text, value, positive_is_plus=True):
    value = _as_int(value, 0)
    if not value:
        return None
    if value > 0:
        sign = "+" if positive_is_plus else "-"
        return "%s %s%s" % (label_text, sign, value)
    sign = "-" if positive_is_plus else "+"
    return "%s %s%s" % (label_text, sign, abs(value))


def _ram_cost_modifier_line(prefix, value):
    try:
        modifier = float(value)
    except Exception:
        return None
    if 0.99 <= modifier <= 1.01:
        return None
    token = "RAM+" if modifier < 1 else "RAM-"
    pct = int(abs(1.0 - modifier) * 100)
    return prefix + ("%s%s%%" % (token, pct) if pct else token)


def _log_entries(result):
    log = result.get("log", [])
    if isinstance(log, str):
        return [log]
    return log or []


def _log_has_for_actor(result, actor, *needles):
    actor = str(actor or "").lower()
    for entry in _log_entries(result):
        text = str(entry).lower()
        if actor in text:
            for needle in needles:
                if needle in text:
                    return True
    return False


def _effect_actor(effect):
    if not isinstance(effect, dict):
        return None
    raw = (effect.get("actor") or effect.get("target") or effect.get("target_role") or
           effect.get("player_role") or effect.get("role"))
    if raw:
        raw = str(raw).lower()
        if raw.startswith("attack"):
            return "attacker"
        if raw.startswith("defend"):
            return "defender"
    return None


def _round_effect_text(effect):
    text = _effect_text(effect, compact=True)
    if text.startswith("BUFF_"):
        return "BUFF"
    return text


def _active_effect_lines(result, actor, prefix=""):
    lines = []
    effects = result.get("active_effects", []) or []
    if isinstance(effects, dict):
        effects = effects.get(actor) or effects.get(actor + "_effects") or effects.get("effects") or []
    for effect in effects:
        effect_actor = _effect_actor(effect)
        if effect_actor is not None and effect_actor != actor:
            continue
        text = _round_effect_text(effect)
        if text and text != "EFFE":
            _append_unique(lines, (prefix + text)[:16])
    return lines


def _status_lines_from_fields(result, actor, prefix=""):
    lines = []
    if _actor_flag(result, actor, "silenced") or _log_has_for_actor(result, actor, "silence", "silenced"):
        _append_unique(lines, prefix + "SIL")
    if _actor_flag(result, actor, "item_lockout") or _log_has_for_actor(result, actor, "item lock", "lockout"):
        _append_unique(lines, prefix + "LOCK")
    if _actor_field(result, actor, "defense_bonus"):
        _append_unique(lines, _line_delta(prefix + "DEF", _actor_field(result, actor, "defense_bonus")))
    elif _log_has_for_actor(result, actor, "def-", "defense debuff", "debuff"):
        _append_unique(lines, prefix + "DEF-")
    if _actor_field(result, actor, "attack_bonus"):
        _append_unique(lines, _line_delta(prefix + "ATK", _actor_field(result, actor, "attack_bonus")))
    elif _log_has_for_actor(result, actor, "atk-", "attack debuff"):
        _append_unique(lines, prefix + "ATK-")
    _append_unique(lines, _ram_cost_modifier_line(prefix, result.get(actor + "_ram_cost_modifier")))
    lines.extend(_active_effect_lines(result, actor, prefix))
    return lines


def _resource_lines_from_fields(result, actor):
    lines = []
    _append_unique(lines, _line_delta("RAM", _actor_field(result, actor, "ram_regen")))
    _append_unique(lines, _line_delta("HEAL", _actor_field(result, actor, "heal")))
    _append_unique(lines, _line_delta("RAM", -_actor_field(result, actor, "ram_cost")))
    _append_unique(lines, _line_delta("DOT", -_actor_field(result, actor, "dot_damage")))
    return lines


def _round_effect_lines(game_state, result, selected_move=None):
    role = _role_for_result(game_state, result)
    local_actor = "attacker" if str(role).startswith("attack") else "defender"
    other_actor = "defender" if local_actor == "attacker" else "attacker"
    damage = stat_value(result, "net_damage")
    lines = _selection_lines(game_state, result, selected_move)
    # Combine mitigation and damage to leave scarce EPD message rows for resource
    # and status effects while preserving the required MIT line prefix.
    lines[1] = "%s %s:%s" % (lines[1], "DMG" if local_actor == "attacker" else "HIT", damage)

    for line_text in _resource_lines_from_fields(result, local_actor):
        _append_unique(lines, line_text)
    for line_text in _status_lines_from_fields(result, local_actor):
        _append_unique(lines, line_text)

    # Opponent-side outcomes are lower priority and prefixed so they do not look
    # like private local status. They are shown only when the resolved result or
    # log already implies an applied combat effect.
    for line_text in _status_lines_from_fields(result, other_actor, "FOE "):
        _append_unique(lines, line_text)
    if _log_has_for_actor(result, local_actor, "damage to " + local_actor):
        _append_unique(lines, "ITM HIT")
    return lines


def round_result_lines(result, game_state, selected_move=None, max_lines=ROUND_RESULT_MAX_LINES):
    """Return compact durable EPD lines for a resolved CorpoBreach round."""
    return _round_effect_lines(game_state, result, selected_move)[:max_lines]


def show_round_result(lcd, epd, result, game_state, selected_move=None,
                      a="Back", b="Up", c="Down", d="Select", update_lcd=True):
    if update_lcd:
        clear_screen(lcd)
        g = Group()
        g.append(label("Round complete", 2, 8, CYAN))
        g.append(label("See EPD result", 2, 30, WHITE))
        lcd.root_group.append(g)
    show_combat_status_epd(epd, game_state, a=a, b=b, c=c, d=d,
                           status_lines=round_result_lines(result, game_state, selected_move))


def show_match_outcome(lcd, epd, payload, fallback_state=None, update_epd=True):
    final_state = payload.get("final_game_state") or payload.get("game_state") or fallback_state or {}
    outcome = payload.get("outcome") or payload.get("status") or "match_over"
    title_map = {
        "victory": "Victory!",
        "defeat": "Defeat",
        "opponent_exited": "Forfeit win",
        "exited": "Forfeited",
        "match_abandoned": "Abandoned",
    }
    title = title_map.get(outcome, title_map.get(payload.get("status"), "Match over"))
    xp = payload.get("xp_gained") or payload.get("xp_awarded") or payload.get("xp")
    body = payload.get("message", "Match concluded")
    if xp is not None:
        body = body + " XP +%s" % xp
    clear_screen(lcd)
    g = Group()
    g.append(center_text_x_plane(lcd, title, y=14, color=GREEN if outcome in ("victory", "opponent_exited") else YELLOW))
    msg = wrap_message(lcd, body, x=2, y=36)
    g.append(msg)
    lcd.root_group.append(g)
    if not update_epd:
        return
    if final_state:
        show_combat_status_epd(epd, final_state, a="Back", b="Up", c="Down", d="Select")
    else:
        draw_button_bar(epd, a="Back", b="Up", c="Down", d="Select")


def short_name(obj):
    if obj is None:
        return "None"
    if isinstance(obj, dict):
        return obj.get("player_name") or obj.get("name") or str(obj.get("id", obj))
    return str(obj)
