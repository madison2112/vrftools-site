"""Unit tests for web.lib.sessions — B-16.

Coverage target: ≥ 95% line coverage on web/lib/sessions.py.
"""

import json
import os
import pickle
import threading
import time

import pytest

import web.lib.sessions as sessions


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_session_dir(tmp_path, monkeypatch):
    """Redirect SESSION_DIR to an isolated temp directory for every test."""
    monkeypatch.setattr(sessions, "SESSION_DIR", str(tmp_path))


# ---------------------------------------------------------------------------
# Test cases — create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_returns_uuid_and_file_exists(self):
        """create() returns a valid UUID string and writes a {sid}.json file."""
        sid = sessions.create({"k": "v"})
        assert isinstance(sid, str), f"Expected str, got {type(sid)}"
        # UUIDs are 36 characters with hyphens.
        assert len(sid) == 36, f"Expected 36-char UUID, got {len(sid)}: {sid!r}"
        assert sid.count("-") == 4, f"Expected 4 hyphens in UUID, got: {sid!r}"

        json_path = os.path.join(sessions.SESSION_DIR, f"{sid}.json")
        assert os.path.isfile(json_path), f"Session file not created: {json_path}"

        # Verify file contents are valid JSON with expected keys.
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["k"] == "v"
        assert isinstance(data["expires"], float)


# ---------------------------------------------------------------------------
# Test cases — get
# ---------------------------------------------------------------------------


class TestGet:
    def test_returns_payload(self):
        """get() returns the stored payload with original keys + expires."""
        sid = sessions.create({"foo": "bar", "num": 42})
        data = sessions.get(sid)
        assert data is not None
        assert data["foo"] == "bar"
        assert data["num"] == 42
        assert isinstance(data["expires"], float)

    def test_returns_none_for_unknown_sid(self):
        """get() returns None for a nonexistent session id, no exception."""
        result = sessions.get("nonexistent-uuid-0000-0000-000000000000")
        assert result is None

    def test_returns_none_for_expired_session(self):
        """get() returns None and unlinks the file for an expired session."""
        sid = sessions.create({"x": 1})
        json_path = os.path.join(sessions.SESSION_DIR, f"{sid}.json")

        # Rewrite the on-disk expires to a past timestamp.
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["expires"] = 100.0  # long ago
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        result = sessions.get(sid)
        assert result is None
        assert not os.path.exists(json_path), (
            "Expired session file should have been unlinked"
        )


# ---------------------------------------------------------------------------
# Test cases — update
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_merges_patch(self):
        """update() merges patch keys into existing session data."""
        sid = sessions.create({"a": 1})
        ok = sessions.update(sid, {"b": 2})
        assert ok is True

        data = sessions.get(sid)
        assert data is not None
        assert data["a"] == 1
        assert data["b"] == 2
        assert isinstance(data["expires"], float)

    def test_on_expired_session_returns_false_and_unlinks(self):
        """update() on an expired session returns False and removes the file."""
        sid = sessions.create({"x": 1})
        json_path = os.path.join(sessions.SESSION_DIR, f"{sid}.json")

        # Mark the session as expired by rewriting the file.
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["expires"] = 100.0  # long ago
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        ok = sessions.update(sid, {"y": 2})
        assert ok is False
        assert not os.path.exists(json_path), (
            "Expired session file should have been unlinked after update"
        )

    def test_on_unknown_sid_returns_false(self):
        """update() returns False for a nonexistent session id."""
        ok = sessions.update("nonexistent-uuid-0000-0000-000000000000", {"a": 1})
        assert ok is False


# ---------------------------------------------------------------------------
# Test cases — delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_removes_session(self):
        """delete() removes the session file and is idempotent."""
        sid = sessions.create({"x": 1})
        json_path = os.path.join(sessions.SESSION_DIR, f"{sid}.json")
        assert os.path.isfile(json_path)

        sessions.delete(sid)
        assert not os.path.exists(json_path)

        # Second delete should not raise.
        sessions.delete(sid)


# ---------------------------------------------------------------------------
# Test cases — _expiry
# ---------------------------------------------------------------------------


class TestExpiry:
    def test_returns_future_timestamp(self):
        """_expiry() returns a float strictly greater than current time."""
        now = time.time()
        expires = sessions._expiry()
        assert isinstance(expires, float)
        assert expires > now, f"Expected future timestamp, got {expires} (now={now})"


# ---------------------------------------------------------------------------
# Test cases — binary round-trip
# ---------------------------------------------------------------------------


class TestBinaryRoundtrip:
    def test_flat_bytes_survive(self):
        """Bytes values round-trip through create/get via the JSON layer."""
        blob = b"\x00\x01\x02\xff" * 256
        sid = sessions.create({"blob": blob})
        data = sessions.get(sid)
        assert data is not None
        assert isinstance(data["blob"], bytes)
        assert data["blob"] == blob

    def test_nested_bytes_survive(self):
        """Bytes nested inside a dict round-trip correctly."""
        payload = {"outer": {"inner_blob": b"\xde\xad\xbe\xef"}}
        sid = sessions.create(payload)
        data = sessions.get(sid)
        assert data is not None
        assert isinstance(data["outer"]["inner_blob"], bytes)
        assert data["outer"]["inner_blob"] == b"\xde\xad\xbe\xef"

    def test_empty_bytes_roundtrip(self):
        """Empty bytes values round-trip correctly."""
        sid = sessions.create({"empty": b""})
        data = sessions.get(sid)
        assert data is not None
        assert data["empty"] == b""


# ---------------------------------------------------------------------------
# Test cases — _encode_binary / _decode_binary
# ---------------------------------------------------------------------------


class TestEncodeDecode:
    def test_non_bytes_values_passthrough(self):
        """Non-bytes values (str, int, float, None, bool) pass through unchanged."""
        payload = {
            "s": "hello",
            "n": 42,
            "f": 3.14,
            "none": None,
            "t": True,
            "f_val": False,
        }
        encoded = sessions._encode_binary(payload)
        decoded = sessions._decode_binary(encoded)
        assert decoded == payload

    def test_list_of_dicts_with_bytes(self):
        """Lists containing dicts with bytes are encoded/decoded correctly."""
        payload = {
            "items": [
                {"name": "a", "data": b"\x01\x02"},
                {"name": "b", "data": b"\x03\x04"},
            ]
        }
        sid = sessions.create(payload)
        data = sessions.get(sid)
        assert data is not None
        assert data["items"][0]["name"] == "a"
        assert data["items"][0]["data"] == b"\x01\x02"
        assert data["items"][1]["data"] == b"\x03\x04"


# ---------------------------------------------------------------------------
# Test cases — legacy pickle migration
# ---------------------------------------------------------------------------


class TestLegacyPickleMigration:
    def test_migrates_pkl_to_json_on_get(self):
        """get() transparently migrates a legacy .pkl file to .json."""
        sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        pkl_path = os.path.join(sessions.SESSION_DIR, f"{sid}.pkl")
        json_path = os.path.join(sessions.SESSION_DIR, f"{sid}.json")

        payload = {"username": "testuser", "role": "admin", "expires": time.time() + 3600}

        os.makedirs(sessions.SESSION_DIR, exist_ok=True)
        with open(pkl_path, "wb") as f:
            pickle.dump(payload, f)
        assert os.path.isfile(pkl_path)

        data = sessions.get(sid)
        assert data is not None
        assert data["username"] == "testuser"
        assert data["role"] == "admin"

        # Migration: .json should now exist, .pkl should be gone.
        assert os.path.isfile(json_path), "JSON file should have been created during migration"
        assert not os.path.exists(pkl_path), "Legacy .pkl file should have been removed after migration"

    def test_migrates_expired_pkl_returns_none(self):
        """get() on an expired .pkl session returns None and unlinks it."""
        sid = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        pkl_path = os.path.join(sessions.SESSION_DIR, f"{sid}.pkl")
        json_path = os.path.join(sessions.SESSION_DIR, f"{sid}.json")

        payload = {"username": "expired", "expires": 100.0}  # long ago

        os.makedirs(sessions.SESSION_DIR, exist_ok=True)
        with open(pkl_path, "wb") as f:
            pickle.dump(payload, f)

        data = sessions.get(sid)
        assert data is None
        assert not os.path.exists(pkl_path), "Expired .pkl should have been unlinked"
        assert not os.path.exists(json_path), "No .json should be created for expired session"


# ---------------------------------------------------------------------------
# Test cases — cleanup loop
# ---------------------------------------------------------------------------


class TestCleanupLoop:
    def test_removes_tmp_files(self, monkeypatch):
        """Cleanup loop removes orphaned .tmp files from crashed atomic writes."""
        os.makedirs(sessions.SESSION_DIR, exist_ok=True)
        tmp_file = os.path.join(sessions.SESSION_DIR, "orphan.tmp")
        with open(tmp_file, "w") as f:
            f.write("junk")
        assert os.path.isfile(tmp_file)

        # Run one iteration of the cleanup loop by monkeypatching
        # time.sleep to raise after one call (loop enters, sleeps, runs,
        # sleeps again → StopIteration escapes).
        calls = []

        def fake_sleep(seconds):
            calls.append(seconds)
            if len(calls) >= 2:
                raise StopIteration

        monkeypatch.setattr(time, "sleep", fake_sleep)

        try:
            sessions._cleanup_loop()
        except StopIteration:
            pass

        assert not os.path.exists(tmp_file), "Orphaned .tmp file should be cleaned up"

    def test_removes_expired_json_sessions(self, monkeypatch):
        """Cleanup loop removes expired .json session files."""
        os.makedirs(sessions.SESSION_DIR, exist_ok=True)
        expired_json = os.path.join(sessions.SESSION_DIR, "expired.json")
        with open(expired_json, "w", encoding="utf-8") as f:
            json.dump({"expires": 100.0}, f)
        assert os.path.isfile(expired_json)

        calls = []

        def fake_sleep(seconds):
            calls.append(seconds)
            if len(calls) >= 2:
                raise StopIteration

        monkeypatch.setattr(time, "sleep", fake_sleep)

        try:
            sessions._cleanup_loop()
        except StopIteration:
            pass

        assert not os.path.exists(expired_json), "Expired .json should be cleaned up"

    def test_removes_expired_pkl_sessions(self, monkeypatch):
        """Cleanup loop removes expired .pkl session files."""
        os.makedirs(sessions.SESSION_DIR, exist_ok=True)
        expired_pkl = os.path.join(sessions.SESSION_DIR, "expired.pkl")
        with open(expired_pkl, "wb") as f:
            pickle.dump({"expires": 100.0}, f)
        assert os.path.isfile(expired_pkl)

        calls = []

        def fake_sleep(seconds):
            calls.append(seconds)
            if len(calls) >= 2:
                raise StopIteration

        monkeypatch.setattr(time, "sleep", fake_sleep)

        try:
            sessions._cleanup_loop()
        except StopIteration:
            pass

        assert not os.path.exists(expired_pkl), "Expired .pkl should be cleaned up"

    def test_keeps_valid_sessions(self, monkeypatch):
        """Cleanup loop does not remove non-expired sessions or unrelated files."""
        os.makedirs(sessions.SESSION_DIR, exist_ok=True)
        valid_json = os.path.join(sessions.SESSION_DIR, "valid.json")
        with open(valid_json, "w", encoding="utf-8") as f:
            json.dump({"expires": time.time() + 3600}, f)
        assert os.path.isfile(valid_json)

        calls = []

        def fake_sleep(seconds):
            calls.append(seconds)
            if len(calls) >= 2:
                raise StopIteration

        monkeypatch.setattr(time, "sleep", fake_sleep)

        try:
            sessions._cleanup_loop()
        except StopIteration:
            pass

        assert os.path.isfile(valid_json), "Non-expired .json session should NOT be removed"

    def test_survives_corrupt_json_file(self, monkeypatch):
        """Cleanup loop catches exceptions when a .json file is unreadable."""
        os.makedirs(sessions.SESSION_DIR, exist_ok=True)
        corrupt_json = os.path.join(sessions.SESSION_DIR, "corrupt.json")
        with open(corrupt_json, "w", encoding="utf-8") as f:
            f.write("not valid json {{{")
        assert os.path.isfile(corrupt_json)

        calls = []

        def fake_sleep(seconds):
            calls.append(seconds)
            if len(calls) >= 2:
                raise StopIteration

        monkeypatch.setattr(time, "sleep", fake_sleep)

        # Should not crash — the except Exception swallows it.
        try:
            sessions._cleanup_loop()
        except StopIteration:
            pass

        # Corrupt file is left alone (cleanup couldn't parse it).
        assert os.path.isfile(corrupt_json), "Corrupt .json should survive cleanup"

    def test_survives_corrupt_pkl_file(self, monkeypatch):
        """Cleanup loop catches exceptions when a .pkl file is unreadable."""
        os.makedirs(sessions.SESSION_DIR, exist_ok=True)
        corrupt_pkl = os.path.join(sessions.SESSION_DIR, "corrupt.pkl")
        with open(corrupt_pkl, "wb") as f:
            f.write(b"not valid pickle data")
        assert os.path.isfile(corrupt_pkl)

        calls = []

        def fake_sleep(seconds):
            calls.append(seconds)
            if len(calls) >= 2:
                raise StopIteration

        monkeypatch.setattr(time, "sleep", fake_sleep)

        try:
            sessions._cleanup_loop()
        except StopIteration:
            pass

        assert os.path.isfile(corrupt_pkl), "Corrupt .pkl should survive cleanup"

    def test_survives_listdir_failure(self, monkeypatch):
        """Cleanup loop outer except catches exceptions from os.listdir."""
        os.makedirs(sessions.SESSION_DIR, exist_ok=True)

        monkeypatch.setattr(os, "listdir", lambda _: (_ for _ in ()).throw(OSError("permission denied")))

        calls = []

        def fake_sleep(seconds):
            calls.append(seconds)
            if len(calls) >= 2:
                raise StopIteration

        monkeypatch.setattr(time, "sleep", fake_sleep)

        # Should not crash — the outer except Exception swallows it.
        try:
            sessions._cleanup_loop()
        except StopIteration:
            pass


# ---------------------------------------------------------------------------
# Test cases — error-cleanup paths (write failures during atomic saves)
# ---------------------------------------------------------------------------


class TestAtomicWriteErrorCleanup:
    def test_create_cleans_up_temp_file_on_write_failure(self, monkeypatch):
        """When json.dump raises during create(), the temp file is unlinked."""
        os.makedirs(sessions.SESSION_DIR, exist_ok=True)

        # Capture the temp file path by wrapping mkstemp.
        temp_paths = []
        _orig_mkstemp = sessions.tempfile.mkstemp

        def _capturing_mkstemp(*args, **kwargs):
            fd, path = _orig_mkstemp(*args, **kwargs)
            temp_paths.append(path)
            return fd, path

        monkeypatch.setattr(sessions.tempfile, "mkstemp", _capturing_mkstemp)

        # Make json.dump fail after the temp file is created.
        monkeypatch.setattr(sessions.json, "dump", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))

        with pytest.raises(OSError, match="disk full"):
            sessions.create({"x": 1})

        assert len(temp_paths) == 1
        assert not os.path.exists(temp_paths[0]), "Temp file should be cleaned up after write failure"

    def test_update_cleans_up_temp_file_on_write_failure(self, monkeypatch):
        """When json.dump raises during update(), the temp file is unlinked."""
        sid = sessions.create({"x": 1})

        temp_paths = []
        _orig_mkstemp = sessions.tempfile.mkstemp

        def _capturing_mkstemp(*args, **kwargs):
            fd, path = _orig_mkstemp(*args, **kwargs)
            temp_paths.append(path)
            return fd, path

        monkeypatch.setattr(sessions.tempfile, "mkstemp", _capturing_mkstemp)
        monkeypatch.setattr(sessions.json, "dump", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))

        with pytest.raises(OSError, match="disk full"):
            sessions.update(sid, {"y": 2})

        assert len(temp_paths) == 1
        assert not os.path.exists(temp_paths[0]), "Temp file should be cleaned up after update write failure"

    def test_create_survives_unlink_failure_in_error_handler(self, monkeypatch):
        """When both json.dump and os.unlink fail during create(), the
        OSError from unlink is swallowed (only the original error propagates)."""
        os.makedirs(sessions.SESSION_DIR, exist_ok=True)

        _orig_unlink = os.unlink
        _unlink_errors = []
        _session_dir = sessions.SESSION_DIR

        def _failing_unlink(path):
            # Only fail for paths inside the session dir (avoid breaking
            # pytest's tmp_path teardown).
            if path.startswith(_session_dir):
                _unlink_errors.append(path)
                raise OSError("unlink also failed")
            return _orig_unlink(path)

        monkeypatch.setattr(os, "unlink", _failing_unlink)
        monkeypatch.setattr(sessions.json, "dump", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))

        with pytest.raises(OSError, match="disk full"):
            sessions.create({"x": 1})

        assert len(_unlink_errors) >= 1, "os.unlink should have been attempted during cleanup"


# ---------------------------------------------------------------------------
# Test cases — legacy pickle migration error paths
# ---------------------------------------------------------------------------


class TestLegacyMigrationErrorPaths:
    def test_migration_returns_data_even_when_json_save_fails(self, monkeypatch):
        """When the JSON re-save during pickle migration fails, get() still
        returns the legacy data (the except Exception: pass on line 207)."""
        sid = "cccccccc-dddd-eeee-ffff-000000000000"
        pkl_path = os.path.join(sessions.SESSION_DIR, f"{sid}.pkl")

        payload = {"username": "migrate_me", "expires": time.time() + 3600}

        os.makedirs(sessions.SESSION_DIR, exist_ok=True)
        with open(pkl_path, "wb") as f:
            pickle.dump(payload, f)

        # Make json.dump fail during the migration re-save.
        monkeypatch.setattr(sessions.json, "dump", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))

        # get() should still return the data despite the migration failure.
        data = sessions.get(sid)
        assert data is not None
        assert data["username"] == "migrate_me"

        # The .pkl should NOT have been removed (migration didn't complete).
        assert os.path.isfile(pkl_path), (
            "Legacy .pkl should remain if JSON migration failed"
        )

        # The .json should NOT exist (migration failed before atomic replace).
        json_path = os.path.join(sessions.SESSION_DIR, f"{sid}.json")
        assert not os.path.exists(json_path), (
            "No .json should exist when migration save failed"
        )


# ---------------------------------------------------------------------------
# Test cases — concurrent update
# ---------------------------------------------------------------------------


class TestConcurrentUpdate:
    @pytest.mark.xfail(
        reason=(
            "Known lost-update race: update() does read-modify-write without locking. "
            "Two threads can both read the same base state, each modify different keys, "
            "and the second atomic write overwrites the first. This is a real concurrency "
            "bug (no write-intent locking), not a test flake."
        ),
        strict=True,
    )
    def test_no_lost_writes_under_concurrent_updates(self):
        """Two threads concurrently updating distinct keys — final session
        should carry both keys.  This test exercises the B-14 atomic-write
        pattern to confirm (or expose) the read-modify-write race."""
        sid = sessions.create({})
        iterations = 20
        barrier = threading.Barrier(2, timeout=5)

        def updater(thread_id, key):
            barrier.wait()
            for i in range(iterations):
                sessions.update(sid, {key: i})

        t0 = threading.Thread(target=updater, args=(0, "thread_0_count"))
        t1 = threading.Thread(target=updater, args=(1, "thread_1_count"))
        t0.start()
        t1.start()
        t0.join()
        t1.join()

        data = sessions.get(sid)
        assert data is not None
        assert "thread_0_count" in data, (
            "thread_0_count missing — lost-update race confirmed"
        )
        assert "thread_1_count" in data, (
            "thread_1_count missing — lost-update race confirmed"
        )
        # Both should be at (or near) the max value written.
        assert data["thread_0_count"] == iterations - 1, (
            f"Expected {iterations - 1}, got {data['thread_0_count']}"
        )
        assert data["thread_1_count"] == iterations - 1, (
            f"Expected {iterations - 1}, got {data['thread_1_count']}"
        )
