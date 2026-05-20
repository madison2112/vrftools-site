"""
File-based session store — works correctly across multiple gunicorn workers.
Each session is a pickle file in SESSION_DIR.

Sessions expire at 1:00 AM Pacific Standard Time (UTC-8) nightly, rather
than on a rolling TTL. Every update refreshes the expiry to the next
1:00 AM PST, so active sessions survive across the day.
"""

import os
import pickle
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
    return os.path.join(SESSION_DIR, f"{sid}.pkl")


def _cleanup_loop():
    while True:
        time.sleep(300)
        try:
            now = time.time()
            for fname in os.listdir(SESSION_DIR):
                path = os.path.join(SESSION_DIR, fname)
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
    with open(_session_path(sid), "wb") as f:
        pickle.dump(payload, f)
    return sid


def get(sid: str) -> dict | None:
    try:
        with open(_session_path(sid), "rb") as f:
            data = pickle.load(f)
        if data.get("expires", 0) <= time.time():
            os.unlink(_session_path(sid))
            return None
        return data
    except (FileNotFoundError, pickle.UnpicklingError, EOFError):
        return None


def update(sid: str, patch: dict) -> bool:
    path = _session_path(sid)
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
        if data.get("expires", 0) <= time.time():
            os.unlink(path)
            return False
        data.update(patch)
        data["expires"] = _expiry()
        with open(path, "wb") as f:
            pickle.dump(data, f)
        return True
    except (FileNotFoundError, pickle.UnpicklingError, EOFError):
        return False


def delete(sid: str):
    try:
        os.unlink(_session_path(sid))
    except FileNotFoundError:
        pass
