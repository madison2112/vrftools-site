"""
File-based session store — works correctly across multiple gunicorn workers.
Each session is a pickle file in SESSION_DIR, auto-expired after TTL seconds.
"""
import os
import pickle
import threading
import time
import uuid

SESSION_DIR = "/tmp/ccct-sessions"
_TTL = 3600


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
    payload = {**data, "expires": time.time() + _TTL}
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
        data["expires"] = time.time() + _TTL
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
