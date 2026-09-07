import asyncio
import microcontroller
import supervisor
import time

from displayio import Group
from terminalio import FONT
from adafruit_display_text.label import Label

import badge.buttons as hw_buttons
from badge.buttons import all_tasks
import badge.events as evt
from badge.events import BTN_A_DOWNUP, BTN_B_DOWNUP, BTN_C_DOWNUP, BTN_D_DOWNUP
from badge.constants import CYAN, GREEN, RED, WHITE, YELLOW
from badge.neopixels import neopixels_off, set_neopixel
from badge.screens import LCD, EPD, clear_screen, epd_print_exception
from badge.wifi import WIFI
from scrollable_list import ScrollableList

from apps.corpo_breach.game.api import (
    APP_STATUS_ERROR,
    EVENT_MATCH_ABANDONED,
    EVENT_PLAYER_NOT_IN_QUEUE,
    EVENT_ROUND_COMPLETE,
    RPGApi,
    RPGApiError,
    api_message,
    is_server_error,
)
from apps.corpo_breach.game.display import (
    ability_description_lines,
    ability_label,
    ability_mitigation_lines,
    ability_side,
    ability_style,
    draw_button_bar,
    effect_summary,
    effects_for_player,
    item_description_lines,
    item_label,
    item_style,
    item_usable,
    label,
    loadout_label,
    loadout_style,
    reset_epd_signature_cache,
    rpg_error_message,
    show_combat_state,
    show_combat_status_epd,
    show_match_outcome,
    show_message,
    show_player_status_epd,
    show_round_result,
    round_result_lines,
    side_style,
)

supervisor.runtime.autoreload = False

SIDES = ["PHYSICAL", "NETWORK", "SOCIAL", "WIRELESS", "SUPPLY"]
MOVES = ["basic", "ability", "item", "pass"]
POLL_SECONDS = 2
QUEUE_POLLS = 30
INTENT_POLLS = 30
MATCH_POLLS = 45
EPD_BUTTONS = {"a": "Back", "b": "Up", "c": "Down", "d": "Select"}

# Issue #25 stretch feature toggle. Set to False (or delete loadout_flow()
# and these API/display helpers) to remove badge-side loadout management if the
# app grows too large for the target CircuitPython build.
ENABLE_BADGE_LOADOUT = True
LOADOUT_CACHE = []


def _message(payload, default=""):
    return api_message(payload, default)


async def _show_server_recovery(title="Server error"):
    """Show a safe LCD-only recovery notice for HTTP 5xx failures.

    Do not call exit_match() here; the server match should remain authoritative
    so the player can re-enter combat from the main menu once the server recovers.
    """
    show_message(LCD, title, "Match preserved. Try again.", YELLOW)
    await wait_button(timeout=1.8)


def _player_from_state(payload):
    """Normalize RPG API responses into a badge-safe player summary."""
    if not payload:
        return None
    if payload.get("player"):
        return payload["player"]
    if payload.get("player_state"):
        return payload["player_state"]
    if payload.get("you"):
        return payload["you"]
    if payload.get("match") and payload["match"].get("you"):
        return payload["match"]["you"]
    return None


def _game_state(payload):
    if not payload:
        return None
    return payload.get("game_state") or payload.get("match") or payload.get("final_game_state")


def _active_effect_list(payload):
    if isinstance(payload, list):
        return payload
    if not payload:
        return None
    if payload.get("success") is False or payload.get("status_code") == APP_STATUS_ERROR:
        return None
    for key in ("active_effects", "effects", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    player = _player_from_state(payload)
    return effects_for_player(player) if player else []


def _attach_active_effects(game_state, effects):
    if game_state is not None and effects is not None:
        game_state.setdefault("you", {})["active_effects"] = effects
    return game_state


def _refresh_active_effects(api, game_state):
    payload = api.active_effects()
    return _attach_active_effects(game_state, _active_effect_list(payload))


def _effect_key(effect):
    if isinstance(effect, dict):
        raw = effect.get("effect_type") or effect.get("type") or effect.get("name") or ""
    else:
        raw = effect
    return str(raw).upper()


def _has_effect(effects, *names):
    names = tuple(str(name).upper() for name in names)
    for effect in effects:
        key = _effect_key(effect)
        if key in names:
            return True
    return False


def _current_ram(game_state):
    return game_state.get("you", {}).get("stats", {}).get("current_ram", 0)


def _as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _ability_selectable(ability, current_ram, blocked=False):
    if blocked or ability.get("equipped", True) is False:
        return False
    return _as_int(ability.get("ram_cost"), 0) <= _as_int(current_ram, 0)


def _opponent_level(row):
    level = row.get("level", row.get("lvl"))
    stats = row.get("stats") or {}
    player = row.get("player") or {}
    if level is None and isinstance(stats, dict):
        level = stats.get("level")
    if level is None and isinstance(player, dict):
        level = player.get("level")
    return level


def _level_text(level):
    try:
        value = int(level)
        if value < 0:
            value = 0
        if value > 99:
            value = 99
        level = "%02d" % value
    except Exception:
        level = str(level)[:2]
    return ("Lv:" + level)[:5]


def _opponent_text(row):
    name = str(row.get("player_name", "Player"))
    level = _opponent_level(row)
    if level is None:
        return name[:20]
    level = _level_text(level)
    return "%-14s %5s" % (name[:14], level)


def _ability_id(ability):
    return ability.get("ability_id", ability.get("id"))


def _ability_type(ability):
    return str(ability.get("ability_type") or ability.get("type") or "").upper()


def _ability_role_prefixes(role):
    role = str(role or "").lower()
    if role.startswith("attack"):
        return ("OFF", "ATTACK")
    if role.startswith("defend"):
        return ("DEF", "DEFEND")
    return ()


def _ability_allowed_for_role(ability, role):
    kind = _ability_type(ability)
    prefixes = _ability_role_prefixes(role)
    return bool(kind and prefixes and kind.startswith(prefixes))


def _abilities_for_role(abilities, role):
    return [ability for ability in abilities or [] if _ability_allowed_for_role(ability, role)]


def _side_index(row):
    side = ability_side(row) if isinstance(row, dict) else row
    try:
        return SIDES.index(str(side).upper())
    except ValueError:
        return len(SIDES)


def _sort_by_side(rows):
    return sorted(rows or [], key=lambda row: (_side_index(row), str(row.get("name", "") if isinstance(row, dict) else row)))


def _indexed_rows(rows, key):
    return [{key: row, "row_index": idx} for idx, row in enumerate(rows or [])]


def _side_rows():
    return _indexed_rows(SIDES, "side")


def _side_row_text(row):
    return str(row.get("side", ""))[:20]


def _ability_rows(abilities):
    return _indexed_rows(abilities, "ability")


def _ability_row_text(row):
    return ability_label(row.get("ability", row))


def _loadout_error(payload):
    text = rpg_error_message(payload)
    low = str(text).lower()
    if "storage" in low or "limit" in low or "full" in low:
        return "Storage full"
    if "locked" in low or "unlock" in low:
        return "Ability locked"
    if "active" in low or "match" in low or "combat" in low:
        return "Finish match first"
    return text[:40]


def _remember_loadout_candidate(ability):
    aid = _ability_id(ability)
    if aid is None:
        return
    for existing in LOADOUT_CACHE:
        if _ability_id(existing) == aid:
            existing.update(ability)
            existing["is_equipped"] = False
            return
    cached = dict(ability)
    cached["is_equipped"] = False
    LOADOUT_CACHE.append(cached)


def _loadout_rows(payload):
    rows = []
    seen = set()

    def add_many(items, action, equipped):
        for ability in items or []:
            aid = _ability_id(ability)
            if aid in seen:
                continue
            if aid is not None:
                seen.add(aid)
            row_ability = dict(ability)
            row_ability["is_equipped"] = equipped
            rows.append({"ability": row_ability, "action": action,
                         "equipped": equipped,
                         "unavailable": row_ability.get("unlocked", True) is False})

    # Current server contract returns equipped abilities split by type. The
    # generic keys let this removable badge UI use a richer server payload later
    # without changing the display loop.
    add_many(payload.get("offensive"), "unequip", True)
    add_many(payload.get("defensive"), "unequip", True)
    for key in ("unequipped", "available", "abilities"):
        for ability in payload.get(key, []) or []:
            equipped = ability.get("is_equipped", ability.get("equipped", False))
            add_many([ability], "unequip" if equipped else "equip", bool(equipped))
    for ability in LOADOUT_CACHE:
        aid = _ability_id(ability)
        if aid not in seen:
            rows.append({"ability": ability, "action": "equip", "equipped": False,
                         "unavailable": ability.get("unlocked", True) is False})
    return sorted(rows, key=lambda row: (_side_index(row.get("ability", {})), loadout_label(row)))


def _loadout_title(payload, rows):
    storage = payload.get("storage", "?")
    off = 0
    deff = 0
    for row in rows:
        if not row.get("equipped"):
            continue
        kind = _ability_type(row.get("ability", {}))
        if kind.startswith("OFF"):
            off += 1
        elif kind.startswith("DEF"):
            deff += 1
    return "Load O%s/%s D%s/%s" % (off, storage, deff, storage)


_BUTTON_LOCKS = {}


async def wait_button(timeout=None):
    """Return the next button action using direct pressed-state polling.

    Down/up event sequences are easy to miss in the simulator when a press starts
    before a screen has entered its wait loop. Polling catches already-held
    buttons and returns on press; per-button locks prevent hold-repeat until the
    physical/simulated button is released.
    """
    mapping = (
        ("a", hw_buttons.BTN_A, BTN_A_DOWNUP),
        ("b", hw_buttons.BTN_B, BTN_B_DOWNUP),
        ("c", hw_buttons.BTN_C, BTN_C_DOWNUP),
        ("d", hw_buttons.BTN_D, BTN_D_DOWNUP),
    )
    start = supervisor.ticks_ms()
    while True:
        for name, button, event in mapping:
            pressed = button.getstate_func()
            if not pressed:
                _BUTTON_LOCKS[name] = False
            elif not _BUTTON_LOCKS.get(name):
                _BUTTON_LOCKS[name] = True
                return event
        if timeout is not None and supervisor.ticks_ms() - start >= int(timeout * 1000):
            return None
        await asyncio.sleep(0.02)


async def confirm_choice(title, row, description_fn, epd_game_state=None, lcd_description_fn=None,
                         a_label="Back", d_label="Select", update_epd=True):
    """Render a S4/S7 confirmation step for a selected combat choice."""
    lines = description_fn(row) or [title]
    lcd_lines = (lcd_description_fn(row) if lcd_description_fn else lines) or [title]
    clear_screen(LCD)
    root = Group()
    root.append(label(title, 2, 8, CYAN))
    for idx, line in enumerate(lcd_lines[:5]):
        root.append(label(str(line)[:20], 2, 24 + idx * 14, WHITE))
    root.append(label(("S4 " + a_label)[:20], 2, 104, YELLOW))
    root.append(label(("S7 " + d_label)[:20], 64, 104, GREEN))
    LCD.root_group.append(root)
    if update_epd:
        if epd_game_state:
            show_combat_status_epd(EPD, epd_game_state, a=a_label, b="Up", c="Down", d=d_label, status_lines=lines)
        else:
            draw_button_bar(EPD, a=a_label, b="Up", c="Down", d=d_label)
    while True:
        btn = await wait_button()
        if btn == BTN_A_DOWNUP:
            return False
        if btn == BTN_D_DOWNUP:
            return True


def _forfeit_description(_row):
    return ["Forfeit match?", "S7 confirms exit", "S4 cancels"]


async def choose_from_list(title, items, text_fn, style_fn=None, epd_game_state=None,
                           epd_lines=None, epd_buttons=None, update_epd=True):
    epd_buttons = epd_buttons or EPD_BUTTONS
    if not items:
        show_message(LCD, title, "Nothing available")
        if update_epd:
            if epd_game_state:
                show_combat_status_epd(EPD, epd_game_state,
                                       a=epd_buttons.get("a", ""), b=epd_buttons.get("b", ""),
                                       c=epd_buttons.get("c", ""), d=epd_buttons.get("d", ""),
                                       status_lines=epd_lines)
            else:
                draw_button_bar(EPD, a=epd_buttons.get("a", ""), b=epd_buttons.get("b", ""),
                                c=epd_buttons.get("c", ""), d=epd_buttons.get("d", ""))
        await wait_button()
        return None

    clear_screen(LCD)
    root = Group()
    root.append(label(title, 2, 8, CYAN))
    lst = ScrollableList(items, text_fn=text_fn, max_visible=6, y_offset=18, max_chars=20,
                         selected_bg=0x666666 if style_fn else 0xaaaaaa,
                         selected_fg=None if style_fn else 0x111111,
                         style_fn=style_fn,
                         wrap=True, loop_scroll=False)
    root.append(lst.get_group())
    LCD.root_group.append(root)
    # List text stays on the LCD, but EPD button labels still need to match the
    # active controls. Re-render with durable/non-transient message lines only.
    if update_epd:
        if epd_game_state:
            show_combat_status_epd(EPD, epd_game_state,
                                   a=epd_buttons.get("a", ""), b=epd_buttons.get("b", ""),
                                   c=epd_buttons.get("c", ""), d=epd_buttons.get("d", ""),
                                   status_lines=epd_lines)
        else:
            draw_button_bar(EPD, a=epd_buttons.get("a", ""), b=epd_buttons.get("b", ""),
                            c=epd_buttons.get("c", ""), d=epd_buttons.get("d", ""))

    while True:
        lst.update()
        btn = await wait_button(timeout=0.1)
        if btn == BTN_A_DOWNUP:
            return None
        elif btn == BTN_B_DOWNUP:
            lst.input(True)
        elif btn == BTN_C_DOWNUP:
            lst.input(False)
        elif btn == BTN_D_DOWNUP:
            return lst.get_selected()


async def pick_move(game_state, epd_lines=None, update_epd_fn=None):
    abilities = game_state.get("you", {}).get("abilities", [])
    inventory = game_state.get("you", {}).get("inventory", [])
    moves = [("Basic", "basic"), ("Ability", "ability"), ("Item", "item"), ("Pass", "pass")]

    while True:
        clear_screen(LCD)
        root = Group()
        root.append(label("R%s %s" % (game_state.get("round", "?"), game_state.get("your_role", "?")), 2, 8, CYAN))
        lst = ScrollableList(moves, text_fn=lambda row: row[0], max_visible=4, y_offset=24, max_chars=20,
                             wrap=True, loop_scroll=False)
        root.append(lst.get_group())
        LCD.root_group.append(root)
        # Keep prompt text on the LCD, but update EPD button labels for the
        # current controls. Preserve durable result/status lines when provided.
        if update_epd_fn:
            update_epd_fn(game_state, lines=epd_lines)
        else:
            show_combat_status_epd(EPD, game_state, a=EPD_BUTTONS["a"], b=EPD_BUTTONS["b"],
                                   c=EPD_BUTTONS["c"], d=EPD_BUTTONS["d"], status_lines=epd_lines)

        while True:
            lst.update()
            btn = await wait_button(timeout=0.1)
            if btn == BTN_A_DOWNUP:
                if await confirm_choice("Confirm forfeit", {}, _forfeit_description, game_state,
                                        a_label="Cancel", d_label="Forfeit", update_epd=False):
                    return {"forfeit": True}
                break
            if btn == BTN_B_DOWNUP:
                lst.input(True)
            elif btn == BTN_C_DOWNUP:
                lst.input(False)
            elif btn == BTN_D_DOWNUP:
                move = lst.get_selected()[1]
                effects = effects_for_player(game_state.get("you", {}))
                if move == "basic":
                    side_row = await choose_from_list("Side", _side_rows(), _side_row_text, side_style,
                                                      epd_game_state=game_state, epd_lines=epd_lines,
                                                      update_epd=False)
                    if side_row:
                        return {"move_type": "basic", "side": side_row.get("side")}
                    break
                if move == "ability":
                    if _has_effect(effects, "SILENCE", "SIL"):
                        show_message(LCD, "Silenced", "Abilities blocked: " + effect_summary(effects, True), YELLOW)
                        await wait_button(timeout=1.2)
                        break
                    current_ram = _current_ram(game_state)
                    role_abilities = _abilities_for_role(abilities, game_state.get("your_role"))
                    while True:
                        ability_row = await choose_from_list("Ability", _ability_rows(_sort_by_side(role_abilities)), _ability_row_text,
                                                             lambda a: ability_style(a, current_ram),
                                                             epd_game_state=game_state, epd_lines=epd_lines,
                                                             update_epd=False)
                        if not ability_row:
                            break
                        ability = ability_row.get("ability", ability_row)
                        if not _ability_selectable(ability, current_ram):
                            show_message(LCD, "Ability blocked", "Need resource %s, have %s" % (ability.get("ram_cost", "?"), current_ram), YELLOW)
                            await wait_button(timeout=1.4)
                            continue
                        if not await confirm_choice("Confirm special", ability, ability_description_lines, game_state, ability_mitigation_lines):
                            continue
                        return {"move_type": "ability", "ability_id": ability.get("id"), "side": ability_side(ability)}
                    break
                if move == "item":
                    if _has_effect(effects, "ITEM_LOCKOUT", "LOCK", "ITEM_LOCK"):
                        show_message(LCD, "Item locked", "Items blocked: " + effect_summary(effects, True), YELLOW)
                        await wait_button(timeout=1.2)
                        break
                    role = game_state.get("your_role")
                    while True:
                        item = await choose_from_list("Item", inventory, item_label,
                                                      lambda i: item_style(i, role),
                                                      epd_game_state=game_state, epd_lines=epd_lines,
                                                      update_epd=False)
                        if not item:
                            break
                        if not item_usable(item, role):
                            show_message(LCD, "Item blocked", "Not usable this turn", YELLOW)
                            await wait_button(timeout=1.4)
                            continue
                        if not await confirm_choice("Confirm item", item, item_description_lines, game_state):
                            continue
                        return {"move_type": "item", "item_id": item.get("id")}
                    break
                if move == "pass":
                    return {"move_type": "pass"}


async def cancel_matchmaking(api):
    show_message(LCD, "Matchmaking", "Leaving matchmaking...", YELLOW)
    payload = api.cancel_matchmaking()
    if payload.get("status_code", 200) >= 400 or payload.get("success") is False:
        show_message(LCD, "Cancel failed", _message(payload, "Returning to menu"), YELLOW)
    else:
        show_message(LCD, "Matchmaking", _message(payload, "Matchmaking cancelled"), GREEN)
    await asyncio.sleep(0.8)
    return payload


def _matchmaking_player(base_player, payload):
    """Keep known local player resources available across queue responses."""
    return _player_from_state(payload) or base_player


def _resource_signature(player_state):
    stats = (player_state or {}).get("stats", {})
    return (
        stats.get("current_hp", stats.get("hp", stats.get("health"))),
        stats.get("max_hp", stats.get("max_health", stats.get("health_max"))),
        stats.get("current_ram", stats.get("ram", stats.get("mana"))),
        stats.get("max_ram", stats.get("max_mana", stats.get("mana_max"))),
    )


async def wait_for_match(api, player_state=None):
    last_wait_epd = _resource_signature(player_state) if player_state else None
    for _ in range(INTENT_POLLS):
        payload = api.check_intent()
        player_state = _matchmaking_player(player_state, payload)
        if player_state:
            wait_epd = _resource_signature(player_state)
            if wait_epd != last_wait_epd:
                # Matchmaking waits are LCD-only; avoid slow EPD refreshes while polling.
                last_wait_epd = wait_epd
        status = payload.get("status")
        event_id = payload.get("event_id")
        if status == "matched" or payload.get("game_session_id") or payload.get("player_state"):
            set_neopixel("a", GREEN)
            await asyncio.sleep(0.25)
            neopixels_off()
            return True
        if event_id in (8, 9, 12) or status in ("expired", "conflict"):
            show_message(LCD, "Matchmaking", _message(payload, "Pick a new opponent"), YELLOW)
            await asyncio.sleep(1.0)
            return False
        show_message(LCD, "Waiting", _message(payload, "Waiting for opponent..."))
        btn = await wait_button(timeout=POLL_SECONDS)
        if btn == BTN_A_DOWNUP:
            await cancel_matchmaking(api)
            return False
    show_message(LCD, "Timeout", "No match yet")
    return False


async def matchmaking_flow(api, resume_queue=False, player_state=None):
    show_message(LCD, "Matchmaking", "Refreshing queue..." if resume_queue else "Joining queue...")
    # Queue/join/search progress is LCD-only. Do not refresh the EPD for these
    # transient matchmaking states.
    payload = api.refresh_queue() if resume_queue else api.find_match()
    player_state = _matchmaking_player(player_state, payload)
    last_search_epd = None

    for _ in range(QUEUE_POLLS):
        if payload.get("status_code") == APP_STATUS_ERROR and payload.get("event_id") == EVENT_PLAYER_NOT_IN_QUEUE:
            show_message(LCD, "Queue expired", "Rejoining matchmaking...", YELLOW)
            payload = api.find_match()

        player_state = _matchmaking_player(player_state, payload)
        players = payload.get("players", [])
        if players:
            opponent = await choose_from_list("Opponents", players, _opponent_text, update_epd=False)
            if opponent is None:
                await cancel_matchmaking(api)
                return False
            show_message(LCD, "Challenge", _opponent_text(opponent))
            intent = api.opponent_select(opponent.get("player_id"))
            if intent.get("status") == "matched" or intent.get("game_session_id") or intent.get("player_state"):
                return True
            if intent.get("event_id") in (8, 9):
                show_message(LCD, "Try again", _message(intent, "Pick another opponent"), YELLOW)
                await asyncio.sleep(1.0)
                payload = api.find_match()
                continue
            return await wait_for_match(api, player_state)

        show_message(LCD, "Searching", "No opponents yet. S4 cancels.")
        if player_state:
            search_epd = _resource_signature(player_state)
            if search_epd != last_search_epd:
                # Search progress is LCD-only; avoid repeated EPD refreshes while polling.
                last_search_epd = search_epd
        btn = await wait_button(timeout=POLL_SECONDS)
        if btn == BTN_A_DOWNUP:
            await cancel_matchmaking(api)
            return False
        payload = api.refresh_queue()
        player_state = _matchmaking_player(player_state, payload)

    await cancel_matchmaking(api)
    show_message(LCD, "No opponents", "Try again later")
    await asyncio.sleep(1.5)
    return False


async def recover_intent(api, intent, player_state=None):
    status = intent.get("status")
    if status == "matched":
        show_message(LCD, "Reconnecting", "Restoring match...", GREEN)
        if await wait_for_match(api):
            await combat_loop(api)
        return
    if status == "waiting":
        show_message(LCD, "Reconnecting", "Waiting for accepted challenge...")
        if await wait_for_match(api):
            await combat_loop(api)
        return
    if status in ("expired", "conflict"):
        show_message(LCD, "Challenge stale", "Returning to matchmaking", YELLOW)
        await asyncio.sleep(1.0)
        if await matchmaking_flow(api, player_state=player_state):
            await combat_loop(api)
        return
    show_message(LCD, "Intent", "Unknown status: %s" % status, YELLOW)
    await asyncio.sleep(1.0)


async def recover_queue(api, player_state=None):
    show_message(LCD, "Reconnecting", "Restoring queue...", CYAN)
    if await matchmaking_flow(api, resume_queue=True, player_state=player_state):
        await combat_loop(api)


def _intent_ready_for_match(intent):
    """Return True only for intent states that should auto-recover to combat."""
    if not intent:
        return False
    return (intent.get("status") == "matched" or
            intent.get("game_session_id") or
            intent.get("player_state"))


async def combat_loop(api):
    last_round = None
    pending_move = None
    last_result_lines = None
    last_epd_signature = None

    def epd_signature(game_state, a=EPD_BUTTONS["a"], b=EPD_BUTTONS["b"],
                      c=EPD_BUTTONS["c"], d=EPD_BUTTONS["d"], lines=None):
        return ((game_state or {}).get("round"), (game_state or {}).get("your_role"),
                _resource_signature((game_state or {}).get("you", {})),
                a, b, c, d, tuple(lines or ()))

    def update_combat_buttons(game_state, a=EPD_BUTTONS["a"], b=EPD_BUTTONS["b"],
                              c=EPD_BUTTONS["c"], d=EPD_BUTTONS["d"], lines=None):
        nonlocal last_epd_signature
        signature = epd_signature(game_state, a, b, c, d, lines)
        if signature != last_epd_signature:
            show_combat_status_epd(EPD, game_state, a=a, b=b, c=c, d=d, status_lines=lines)
            last_epd_signature = signature

    while True:
        payload = api.match_state()
        if is_server_error(payload):
            await _show_server_recovery("Match paused")
            return
        status = payload.get("status")
        if payload.get("event_id") == EVENT_MATCH_ABANDONED:
            payload["status"] = "match_abandoned"
            show_match_outcome(LCD, EPD, payload)
            await wait_button(timeout=2.0)
            return
        game_state = _game_state(payload)
        if not game_state:
            show_message(LCD, "No match", _message(payload, "Match ended"))
            await asyncio.sleep(1.5)
            return
        _refresh_active_effects(api, game_state)

        if status == "match_over" or payload.get("final_game_state"):
            update_outcome_epd = True
            if payload.get("round_result"):
                show_round_result(LCD, EPD, payload.get("round_result"), game_state, pending_move,
                                  update_lcd=False)
                pending_move = None
                update_outcome_epd = False
            show_match_outcome(LCD, EPD, payload, fallback_state=game_state, update_epd=update_outcome_epd)
            set_neopixel("a", GREEN)
            await wait_button()
            neopixels_off()
            return
        current_round = game_state.get("round")
        round_changed = last_round is not None and current_round != last_round
        last_round = current_round

        # Render durable completed-round results, but do not stop on a separate
        # confirmation screen. The summary remains available as EPD message
        # content while subsequent screens update only the button labels.
        if payload.get("round_result"):
            last_result_lines = round_result_lines(payload.get("round_result"), game_state, pending_move)
            show_round_result(LCD, EPD, payload.get("round_result"), game_state, pending_move,
                              update_lcd=False)
            last_epd_signature = epd_signature(game_state, lines=last_result_lines)
            pending_move = None
            await asyncio.sleep(0.8)
            continue
        if status == "round_complete" or payload.get("event_id") == EVENT_ROUND_COMPLETE:
            show_message(LCD, "Round complete", "Waiting for next round", CYAN)
            update_combat_buttons(game_state, lines=last_result_lines)
            await asyncio.sleep(0.8)
            continue
        if round_changed:
            show_message(LCD, "Round advanced", "Choose next move", CYAN)
            update_combat_buttons(game_state, lines=last_result_lines)
            await asyncio.sleep(0.8)

        if game_state.get("you_submitted"):
            show_combat_state(LCD, game_state)
            update_combat_buttons(game_state, lines=last_result_lines)
        if game_state.get("you_submitted"):
            btn = await wait_button(timeout=POLL_SECONDS)
            if btn == BTN_A_DOWNUP:
                result = api.exit_match()
                if is_server_error(result):
                    await _show_server_recovery("Forfeit failed")
                    return
                show_match_outcome(LCD, EPD, result, fallback_state=game_state)
                await wait_button(timeout=2.0)
                return
            continue

        move = await pick_move(game_state, epd_lines=last_result_lines, update_epd_fn=update_combat_buttons)
        if not move:
            continue
        if move.get("forfeit"):
            payload = api.exit_match()
            if is_server_error(payload):
                await _show_server_recovery("Forfeit failed")
                return
            show_match_outcome(LCD, EPD, payload, fallback_state=game_state)
            set_neopixel("d", RED)
            await wait_button(timeout=2.0)
            neopixels_off()
            return

        result = api.submit_move(
            move.get("move_type"),
            side=move.get("side"),
            ability_id=move.get("ability_id"),
            item_id=move.get("item_id"),
        )
        if is_server_error(result):
            await _show_server_recovery("Move not sent")
            return
        if result.get("status_code", 1) == APP_STATUS_ERROR or result.get("status_code", 200) >= 400 or result.get("success") is False:
            show_message(LCD, "Move failed", rpg_error_message(result), RED)
            set_neopixel("d", RED)
        else:
            next_state = _game_state(result) or game_state
            _refresh_active_effects(api, next_state)
            if result.get("round_result"):
                last_result_lines = round_result_lines(result.get("round_result"), next_state, move)
                is_match_over = result.get("status") == "match_over" or result.get("final_game_state")
                show_round_result(LCD, EPD, result.get("round_result"), next_state, move,
                                  update_lcd=is_match_over)
                last_epd_signature = epd_signature(next_state, lines=last_result_lines)
                pending_move = None
                if is_match_over:
                    show_match_outcome(LCD, EPD, result, fallback_state=next_state, update_epd=False)
                    set_neopixel("a", GREEN)
                    await wait_button()
                    neopixels_off()
                    return
            elif result.get("status") == "match_over" or result.get("final_game_state"):
                show_match_outcome(LCD, EPD, result, fallback_state=next_state)
                set_neopixel("a", GREEN)
                await wait_button()
                neopixels_off()
                return
            else:
                pending_move = move
                show_message(LCD, "Move sent", _message(result, "Waiting for foe")[:40], GREEN)
                # LCD-only move-sent feedback; button labels/content are unchanged.
            set_neopixel("a", GREEN)
        await asyncio.sleep(0.8)
        neopixels_off()


async def loadout_flow(api):
    if not ENABLE_BADGE_LOADOUT:
        show_message(LCD, "Loadout", "Use website to equip abilities", YELLOW)
        await wait_button(timeout=1.5)
        return

    while True:
        payload = api.equipped_abilities()
        if payload.get("status_code") == APP_STATUS_ERROR or payload.get("success") is False:
            show_message(LCD, "Loadout", _loadout_error(payload), YELLOW)
            await wait_button()
            return

        rows = _loadout_rows(payload)
        if not rows:
            show_message(LCD, "Loadout", "No equipped abilities. Equip on web first.", YELLOW)
            await wait_button()
            return

        choice = await choose_from_list(_loadout_title(payload, rows), rows, loadout_label, loadout_style)
        if not choice:
            return
        if choice.get("unavailable"):
            show_message(LCD, "Loadout", "Ability locked", YELLOW)
            await wait_button(timeout=1.2)
            continue

        ability = choice.get("ability", {})
        aid = _ability_id(ability)
        if aid is None:
            show_message(LCD, "Loadout", "Missing ability id", RED)
            await wait_button(timeout=1.2)
            continue

        if choice.get("action") == "unequip":
            result = api.unequip_ability(aid)
            if result.get("success") is False or result.get("status_code", 200) >= 400:
                show_message(LCD, "Unequip failed", _loadout_error(result), RED)
            else:
                _remember_loadout_candidate(ability)
                show_message(LCD, "Unequipped", _message(result, ability.get("name", "Ability")), GREEN)
        else:
            result = api.equip_ability(aid)
            if result.get("success") is False or result.get("status_code", 200) >= 400:
                show_message(LCD, "Equip failed", _loadout_error(result), RED)
            else:
                show_message(LCD, "Equipped", _message(result, ability.get("name", "Ability")), GREEN)
        await wait_button(timeout=1.2)


async def main_menu(api):
    last_menu_epd = None
    while True:
        payload = api.player_state()
        if payload.get("match"):
            await combat_loop(api)
            continue

        intent = payload.get("intent")
        if _intent_ready_for_match(intent):
            await recover_intent(api, intent, _player_from_state(payload))
            continue

        pending_matchmaking = bool(payload.get("queue") or intent)
        player = _player_from_state(payload)
        if player:
            effects = _active_effect_list(api.active_effects())
            if effects is not None:
                player["active_effects"] = effects

        if pending_matchmaking:
            title = "Matchmaking paused"
            menu = [("Resume", "resume"), ("Refresh", "refresh"), ("Cancel", "cancel")]
        elif player:
            title = "CorpoBreach"
            menu = [("Find match", "find"), ("Loadout", "loadout"), ("Refresh", "refresh"), ("Exit", "exit")]
        else:
            title = _message(payload, "Register badge" if payload.get("status_code") == APP_STATUS_ERROR else "CorpoBreach")[:20]
            menu = [("Refresh", "refresh"), ("Exit", "exit")]

        clear_screen(LCD)
        root = Group()
        root.append(label(title, 2, 8, CYAN))
        lst = ScrollableList(menu, text_fn=lambda row: row[0], max_visible=5,
                             y_offset=24, max_chars=20,
                             wrap=True, loop_scroll=False)
        root.append(lst.get_group())
        LCD.root_group.append(root)

        if player:
            menu_epd = ("player",) + _resource_signature(player)
            if menu_epd != last_menu_epd:
                show_player_status_epd(EPD, player, a="Back", b="Up", c="Down", d="Select")
                last_menu_epd = menu_epd
        elif last_menu_epd != ("empty",):
            draw_button_bar(EPD, a="Back", b="Up", c="Down", d="Select")
            last_menu_epd = ("empty",)

        while True:
            lst.update()
            btn = await wait_button(timeout=0.1)
            if btn == BTN_A_DOWNUP:
                if pending_matchmaking:
                    await cancel_matchmaking(api)
                else:
                    return
                break
            if btn == BTN_B_DOWNUP:
                lst.input(True)
            elif btn == BTN_C_DOWNUP:
                lst.input(False)
            elif btn == BTN_D_DOWNUP:
                action = lst.get_selected()[1]
                if action == "refresh":
                    break
                if action in ("exit", "cancel"):
                    if pending_matchmaking:
                        await cancel_matchmaking(api)
                    else:
                        return
                    break
                if action == "resume":
                    if payload.get("queue"):
                        await recover_queue(api, player)
                    else:
                        await recover_intent(api, intent, player)
                    break
                if action == "find":
                    if await matchmaking_flow(api, player_state=player):
                        await combat_loop(api)
                    break
                if action == "loadout":
                    await loadout_flow(api)
                    break


async def main():
    all_tasks(interval=0.05)
    evt.start_tasks()
    show_message(LCD, "CorpoBreach", "Connecting WiFi...")
    reset_epd_signature_cache()
    draw_button_bar(EPD, a="Back", b="Up", c="Down", d="Select")
    wifi = WIFI()
    if not wifi.connect_wifi():
        show_message(LCD, "WiFi failed", "Check secrets.py", RED)
        await asyncio.sleep(5)
        return
    await main_menu(RPGApi(wifi))


try:
    asyncio.run(main())
except ImportError:
    epd_print_exception(AttributeError("Secrets file is missing. Please visit recovery."))
    time.sleep(60)
except RPGApiError as e:
    epd_print_exception(e)
    time.sleep(8)
except Exception as e:
    epd_print_exception(e)
    time.sleep(8)
finally:
    neopixels_off()
    microcontroller.reset()
