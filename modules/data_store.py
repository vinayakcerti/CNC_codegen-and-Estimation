import json
import os
import sqlite3
import tempfile
import pandas as pd
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

DATA_DIR = Path(__file__).parent.parent / "data"
PROJECT_ROOT = Path(__file__).parent.parent
LEGACY_DB_PATH = PROJECT_ROOT / "cnc_planner.db"
DB_TIMEOUT_SECONDS = 5


DB_ERRORS = (sqlite3.Error, OSError, pd.errors.DatabaseError)
_DB_PATH_OVERRIDDEN = bool(os.getenv("CNC_PLANNER_DB_PATH"))
_DB_STATUS = {
    "available": True,
    "last_error": None,
    "last_operation": None,
    "path": None,
    "legacy_path": str(LEGACY_DB_PATH),
    "migration_error": None,
    "migrated_from_legacy": False,
}


def _default_db_path():
    override = os.getenv("CNC_PLANNER_DB_PATH")
    if override:
        return Path(override).expanduser()

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "CNC Plan and Process Pro" / "cnc_planner.db"

    return Path.home() / ".cnc_plan_process_pro" / "cnc_planner.db"


def _fallback_db_path():
    return Path(tempfile.gettempdir()) / "CNC Plan and Process Pro" / "cnc_planner.db"


DB_PATH = _default_db_path()
_DB_STATUS["path"] = str(DB_PATH)


def _ensure_db_parent():
    global DB_PATH
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        if _DB_PATH_OVERRIDDEN:
            raise
        fallback_path = _fallback_db_path()
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        _DB_STATUS["migration_error"] = (
            f"Preferred database path unavailable; using fallback {fallback_path}"
        )
        DB_PATH = fallback_path
        _DB_STATUS["path"] = str(DB_PATH)


def _try_migrate_legacy_db():
    if DB_PATH == LEGACY_DB_PATH or DB_PATH.exists() or not LEGACY_DB_PATH.exists():
        return
    try:
        _ensure_db_parent()
        if DB_PATH.exists():
            return
        src = sqlite3.connect(LEGACY_DB_PATH, timeout=DB_TIMEOUT_SECONDS)
        try:
            dst = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT_SECONDS)
            try:
                src.backup(dst)
                _DB_STATUS["migrated_from_legacy"] = True
                _DB_STATUS["migration_error"] = None
            finally:
                dst.close()
        finally:
            src.close()
    except DB_ERRORS as exc:
        _DB_STATUS["migration_error"] = f"{type(exc).__name__}: {exc}"
        print(f"Legacy database migration skipped: {type(exc).__name__}: {exc}")
        try:
            if DB_PATH.exists():
                DB_PATH.unlink()
        except OSError as cleanup_exc:
            _DB_STATUS["migration_error"] += (
                f"; partial cleanup failed: {type(cleanup_exc).__name__}: {cleanup_exc}"
            )


@contextmanager
def _db_connection():
    _ensure_db_parent()
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT_SECONDS)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        yield conn
        conn.commit()
    finally:
        conn.close()


def _log_db_error(operation, exc):
    _DB_STATUS["available"] = False
    _DB_STATUS["last_error"] = f"{type(exc).__name__}: {exc}"
    _DB_STATUS["last_operation"] = operation
    print(f"Local database {operation} failed: {type(exc).__name__}: {exc}")


def _mark_db_available():
    _DB_STATUS["available"] = True
    _DB_STATUS["last_error"] = None
    _DB_STATUS["last_operation"] = None
    _DB_STATUS["path"] = str(DB_PATH)


def get_database_status():
    _DB_STATUS["path"] = str(DB_PATH)
    return dict(_DB_STATUS)


def load_json(filename):
    path = DATA_DIR / filename
    with open(path, "r") as f:
        return json.load(f)


def get_default_materials():
    return load_json("default_materials.json")


def get_default_tools():
    return load_json("default_tools.json")


def get_default_machines():
    return load_json("default_machines.json")


def init_db():
    try:
        _try_migrate_legacy_db()
        with _db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS tools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_number INTEGER,
                    tool_name TEXT,
                    tool_type TEXT,
                    diameter_mm REAL,
                    default_spindle_rpm INTEGER,
                    default_feed_rate_mm_min INTEGER,
                    max_depth_mm REAL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS features (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feature_name TEXT,
                    feature_type TEXT,
                    quantity INTEGER,
                    x_pos REAL,
                    y_pos REAL,
                    diameter REAL,
                    length REAL,
                    width REAL,
                    depth REAL,
                    tolerance_note TEXT,
                    priority INTEGER
                )
            """)
            # Safe migration: add intent columns if missing; existing rows get defaults
            _feat_cols = {row[1] for row in c.execute("PRAGMA table_info(features)").fetchall()}
            if "machining_action" not in _feat_cols:
                c.execute("ALTER TABLE features ADD COLUMN machining_action TEXT DEFAULT 'Machine'")
            if "selected_for_machining" not in _feat_cols:
                c.execute("ALTER TABLE features ADD COLUMN selected_for_machining INTEGER DEFAULT 1")
            c.execute("""
                CREATE TABLE IF NOT EXISTS job_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    stage TEXT,
                    author TEXT,
                    note_type TEXT,
                    note TEXT
                )
            """)
        _mark_db_available()
    except DB_ERRORS as exc:
        _log_db_error("initialization", exc)


def save_tools_to_db(tools):
    try:
        with _db_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM tools")
            for t in tools:
                c.execute("""
                    INSERT INTO tools (tool_number, tool_name, tool_type, diameter_mm,
                        default_spindle_rpm, default_feed_rate_mm_min, max_depth_mm)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (t["tool_number"], t["tool_name"], t["tool_type"], t["diameter_mm"],
                      t["default_spindle_rpm"], t["default_feed_rate_mm_min"], t["max_depth_mm"]))
        _mark_db_available()
    except DB_ERRORS as exc:
        _log_db_error("tool save", exc)


def load_tools_from_db():
    try:
        with _db_connection() as conn:
            df = pd.read_sql_query("SELECT * FROM tools ORDER BY tool_number", conn)
        _mark_db_available()
    except DB_ERRORS as exc:
        _log_db_error("tool load", exc)
        return []
    if df.empty:
        return []
    return df.to_dict("records")


def save_features_to_db(features):
    try:
        with _db_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM features")
            for f in features:
                c.execute("""
                    INSERT INTO features (feature_name, feature_type, quantity, x_pos, y_pos,
                        diameter, length, width, depth, tolerance_note, priority,
                        machining_action, selected_for_machining)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (f["feature_name"], f["feature_type"], f["quantity"], f["x_pos"], f["y_pos"],
                      f["diameter"], f["length"], f["width"], f["depth"], f["tolerance_note"], f["priority"],
                      f.get("machining_action", "Machine"),
                      1 if f.get("selected_for_machining", True) else 0))
        _mark_db_available()
    except DB_ERRORS as exc:
        _log_db_error("feature save", exc)


def load_features_from_db():
    try:
        with _db_connection() as conn:
            df = pd.read_sql_query("SELECT * FROM features ORDER BY priority", conn)
        _mark_db_available()
    except DB_ERRORS as exc:
        _log_db_error("feature load", exc)
        return []
    if df.empty:
        return []
    if "selected_for_machining" in df.columns:
        df["selected_for_machining"] = df["selected_for_machining"].astype(bool)
    if "machining_action" not in df.columns:
        df["machining_action"] = "Machine"
    return df.to_dict("records")


def add_job_note(stage: str, author: str, note_type: str, note: str):
    try:
        with _db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO job_notes (timestamp, stage, author, note_type, note) VALUES (?, ?, ?, ?, ?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), stage, author, note_type, note),
            )
        _mark_db_available()
    except DB_ERRORS as exc:
        _log_db_error("job note save", exc)


def load_job_notes():
    try:
        with _db_connection() as conn:
            df = pd.read_sql_query("SELECT * FROM job_notes ORDER BY id DESC", conn)
        _mark_db_available()
    except DB_ERRORS as exc:
        _log_db_error("job note load", exc)
        return []
    if df.empty:
        return []
    return df.to_dict("records")


def delete_job_note(note_id: int):
    try:
        with _db_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM job_notes WHERE id = ?", (note_id,))
        _mark_db_available()
    except DB_ERRORS as exc:
        _log_db_error("job note delete", exc)


def clear_all_job_notes():
    try:
        with _db_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM job_notes")
        _mark_db_available()
    except DB_ERRORS as exc:
        _log_db_error("job note clear", exc)


init_db()
