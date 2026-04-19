"""
Simple in-memory session store with 1-hour auto-expiry.
Sessions hold uploaded file bytes and parsed state for a user's workflow.
"""
import threading
import time
import uuid


_sessions: dict = {}
_lock = threading.Lock()
_TTL  = 3600  # seconds


def _cleanup_loop():
    while True:
        time.sleep(300)
        now = time.time()
        with _lock:
            expired = [k for k, v in _sessions.items() if v["expires"] <= now]
            for k in expired:
                del _sessions[k]


threading.Thread(target=_cleanup_loop, daemon=True).start()


def create(data: dict) -> str:
    sid = str(uuid.uuid4())
    with _lock:
        _sessions[sid] = {**data, "expires": time.time() + _TTL}
    return sid


def get(sid: str) -> dict | None:
    with _lock:
        s = _sessions.get(sid)
        if s is None:
            return None
        if s["expires"] <= time.time():
            del _sessions[sid]
            return None
        return dict(s)


def update(sid: str, patch: dict) -> bool:
    with _lock:
        s = _sessions.get(sid)
        if s is None or s["expires"] <= time.time():
            return False
        s.update(patch)
        s["expires"] = time.time() + _TTL  # refresh on activity
        return True


def delete(sid: str):
    with _lock:
        _sessions.pop(sid, None)
