"""Small JSON API client for the server-side CorpoBreach RPG endpoints."""

import secrets


# Badge-facing RPG application status/event identifiers mirrored from the
# website's ``src/rpg/api_errors.py``. Keep these stable with the server list;
# badge combat flow uses them to distinguish normal game events from errors.
APP_STATUS_ERROR = 0
APP_STATUS_OK = 1

EVENT_NO_PLAYER = 0
EVENT_PLAYER_NOT_IN_QUEUE = 2
EVENT_MATCH_ABANDONED = 16
EVENT_NOT_ENOUGH_RAM = 20
EVENT_ITEM_NOT_AVAILABLE = 22
EVENT_MOVE_ALREADY_SUBMITTED = 23
EVENT_WAITING_FOR_OPPONENT = 24
EVENT_MATCH_CONCLUDED = 25
EVENT_ROUND_COMPLETE = 26
EVENT_OPPONENT_EXITED = 27
EVENT_EXITED_MATCH = 28
EVENT_ITEM_ATTACK_TURN_ONLY = 33
EVENT_ITEM_DEFENSE_TURN_ONLY = 34
EVENT_SILENCED = 35
EVENT_ITEM_LOCKOUT = 36
EVENT_ABILITY_NOT_EQUIPPED = 37
EVENT_OFFENSIVE_ABILITY_WRONG_TURN = 39
EVENT_DEFENSIVE_ABILITY_WRONG_TURN = 40


class RPGApiError(Exception):
    """Raised when an RPG badge API request fails."""

    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


def normalize_response(payload, http_status):
    """Attach HTTP status metadata without overwriting server app status_code.

    The server's RPG payloads use ``status_code`` as an application success flag
    from ``api_errors.py`` (0/1), while ``response.status_code`` is the actual
    HTTP status. Badge code must check ``http_status``/``server_error`` for 5xx
    recovery so a transient server failure is never confused with a player
    forfeit or normal match exit event.
    """
    if not isinstance(payload, dict):
        payload = {"message": "Unexpected RPG API response", "data": payload}
    payload["http_status"] = http_status
    payload["server_error"] = http_status >= 500
    if http_status >= 500:
        payload.setdefault("status", "server_error")
        payload.setdefault("message", "Server error. Match preserved.")
    return payload


def is_server_error(payload):
    """Return True when a badge API payload came from an HTTP 5xx response."""
    return bool(payload and (payload.get("server_error") or payload.get("http_status", 200) >= 500))


def api_message(payload, default="RPG API request failed"):
    """Return a compact message from a normalized RPG API payload."""
    if not payload:
        return default
    return payload.get("message") or payload.get("error") or payload.get("status") or default


class RPGApi:
    """Wrapper for /rpg/badge/* APIs.

    The website's badge auth decorator expects JSON bodies even for GET
    requests, so every call includes the badge uniqueID in the request JSON.
    """

    BASE_PATH = "rpg/badge/"

    def __init__(self, wifi):
        self.wifi = wifi
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _url(self, endpoint):
        host = self.wifi.host
        if not host.endswith("/"):
            host += "/"
        return host + self.BASE_PATH + endpoint

    def call(self, method, endpoint, data=None, allow_error=False):
        body = {"uniqueID": secrets.UNIQUE_ID}
        if data:
            body.update(data)

        response = self.wifi.requests(
            method=method,
            url=self._url(endpoint),
            headers=self.headers,
            json=body,
        )
        try:
            try:
                payload = response.json()
            except Exception:
                payload = {"message": "Non-JSON response"}
            status_code = response.status_code
        finally:
            try:
                response.close()
            except Exception:
                pass

        payload = normalize_response(payload, status_code)
        if status_code >= 400 and not allow_error:
            raise RPGApiError(api_message(payload), status_code, payload)
        return payload

    def player_state(self):
        return self.call("GET", "player_state", allow_error=True)

    def find_match(self):
        return self.call("POST", "find_match")

    def refresh_queue(self):
        return self.call("GET", "find_match", allow_error=True)

    def cancel_matchmaking(self):
        return self.call("DELETE", "find_match", allow_error=True)

    def opponent_select(self, player_id):
        return self.call("POST", "opponent_select", {"opponent": player_id})

    def check_intent(self):
        return self.call("GET", "check_intent", allow_error=True)

    def match_state(self):
        return self.call("GET", "match_state", allow_error=True)

    def active_effects(self, effect_type=None):
        endpoint = "active_effects"
        if effect_type:
            endpoint += "?type=" + str(effect_type)
        return self.call("GET", endpoint, allow_error=True)

    def equipped_abilities(self):
        return self.call("GET", "equipped_abilities", allow_error=True)

    def equip_ability(self, ability_id):
        return self.call("POST", "equip_ability", {"ability_id": ability_id}, allow_error=True)

    def unequip_ability(self, ability_id):
        return self.call("POST", "unequip_ability", {"ability_id": ability_id}, allow_error=True)

    def submit_move(self, move_type, side=None, ability_id=None, item_id=None):
        data = {"move_type": move_type}
        if side:
            data["side"] = side
        if ability_id is not None:
            data["ability_id"] = ability_id
        if item_id is not None:
            data["item_id"] = item_id
        return self.call("POST", "submit_move", data, allow_error=True)

    def exit_match(self):
        return self.call("POST", "exit_match", allow_error=True)
