"""
File-based session store — works correctly across multiple gunicorn workers.
Each session is a JSON file in SESSION_DIR.

Sessions expire at 1:00 AM Pacific Standard Time (UTC-8) nightly, rather
than on a rolling TTL. Every update refreshes the expiry to the next
1:00 AM PST, so active sessions survive across the day.

Binary payload fields (dat_data, dsbx_data, etc.) are stored as base64
wrapped in a {"__b64__": "…"} sentinel so the entire session file remains
valid JSON.
"""

import base64
import json
import os
import pickle  # retained for backward-compat .pkl migration path
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

SESSION_DIR = "/tmp/ccct-sessions"

# Pacific Standard Time (UTC-8).  Using a fixed offset rather than a
# timezone-aware name to avoid surprises during DST transitions — the
# user explicitly asked for Pacific Standard Time, not Pacific Daylight.
_PST = timezone(timedelta(hours=-8))


def _next_1am_pst() -> float:
    """Unix timestamp of the next 1:00 AM Pacific Standard Time.

    If the current time is before 1:00 AM PST, returns 1:00 AM PST today.
    Otherwise returns 1:00 AM PST tomorrow.
    """
    now = datetime.now(_PST)
    one_am = now.replace(hour=1, minute=0, second=0, microsecond=0)
    if now >= one_am:
        one_am += timedelta(days=1)
    return one_am.timestamp()


def _expiry() -> float:
    return _next_1am_pst()


def _session_path(sid: str) -> str:
    return os.path.join(SESSION_DIR, f"{sid}.json")


def _legacy_session_path(sid: str) -> str:
    """Path for pre-B-15 pickle-based sessions (migration source only)."""
    return os.path.join(SESSION_DIR, f"{sid}.pkl")


def _encode_binary(payload: dict) -> dict:
    """Walk a dict and base64-encode any bytes values.

    Each bytes value is replaced with a sentinel dict:
        {"__b64__": "<base64-encoded string>"}

    Returns a new dict (does not mutate the original).
    """
    result = {}
    for key, value in payload.items():
        if isinstance(value, bytes):
            result[key] = {"__b64__": base64.b64encode(value).decode("ascii")}
        elif isinstance(value, dict):
            result[key] = _encode_binary(value)
        elif isinstance(value, list):
            result[key] = [
                _encode_binary(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def _decode_binary(payload: dict) -> dict:
    """Inverse of _encode_binary: any dict matching {"__b64__": str} is
    decoded back to bytes.
    """
    if len(payload) == 1 and "__b64__" in payload:
        encoded = payload["__b64__"]
        if isinstance(encoded, str):
            return base64.b64decode(encoded)  # type: ignore[return-value]

    result = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            result[key] = _decode_binary(value)
        elif isinstance(value, list):
            result[key] = [
                _decode_binary(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def _cleanup_loop():
    while True:
        time.sleep(300)
        try:
            now = time.time()
            for fname in os.listdir(SESSION_DIR):
                path = os.path.join(SESSION_DIR, fname)
                # Clean up orphaned temp files from crashed atomic writes
                if fname.endswith(".tmp"):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
                    continue
                # Handle both JSON sessions (post-B-15) and pickle
                # sessions (pre-B-15, being migrated on read).
                if fname.endswith(".json"):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if data.get("expires", 0) <= now:
                            os.unlink(path)
                    except Exception:
                        pass
                elif fname.endswith(".pkl"):
                    try:
                        with open(path, "rb") as f:
                            data = pickle.load(f)
                        if data.get("expires", 0) <= now:
                            os.unlink(path)
                    except Exception:
                        pass
        except Exception:
            pass


threading.Thread(target=_cleanup_loop, daemon=True).start()


def create(data: dict) -> str:
    os.makedirs(SESSION_DIR, exist_ok=True)
    sid = str(uuid.uuid4())
    payload = {**data, "expires": _expiry()}
    target = _session_path(sid)
    fd, tmp_path = tempfile.mkstemp(
        dir=SESSION_DIR, suffix=".tmp", prefix=".session_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_encode_binary(payload), f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return sid


def get(sid: str) -> dict | None:
    # 1. Try the current JSON format first.
    json_path = _session_path(sid)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = _decode_binary(json.load(f))
        if data.get("expires", 0) <= time.time():
            os.unlink(json_path)
            return None
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # 2. Fall back to legacy pickle format and migrate on read.
    pkl_path = _legacy_session_path(sid)
    try:
        with open(pkl_path, "rb") as f:
            data = pickle.load(f)
        if data.get("expires", 0) <= time.time():
            os.unlink(pkl_path)
            return None
        # Re-save as JSON, then remove the legacy pickle file.
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=SESSION_DIR, suffix=".tmp", prefix=".session_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(_encode_binary(data), f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, json_path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            os.unlink(pkl_path)
        except Exception:
            pass  # migration failed; still return the data
        return data
    except (FileNotFoundError, pickle.UnpicklingError, EOFError):
        return None


def update(sid: str, patch: dict) -> bool:
    # Reuse get() for read + expiry check + legacy migration.
    data = get(sid)
    if data is None:
        return False

    data.update(patch)
    data["expires"] = _expiry()

    target = _session_path(sid)
    fd, tmp_path = tempfile.mkstemp(
        dir=SESSION_DIR, suffix=".tmp", prefix=".session_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_encode_binary(data), f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return True


def delete(sid: str):
    """Remove a session file, handling both JSON and legacy pickle formats."""
    for path_fn in (_session_path, _legacy_session_path):
        try:
            os.unlink(path_fn(sid))
        except FileNotFoundError:
            pass
