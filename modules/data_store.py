import json
import os
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = Path(__file__).parent.parent / "cnc_planner.db"


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
    conn = sqlite3.connect(DB_PATH)
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
    conn.commit()
    conn.close()


def save_tools_to_db(tools):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM tools")
    for t in tools:
        c.execute("""
            INSERT INTO tools (tool_number, tool_name, tool_type, diameter_mm,
                default_spindle_rpm, default_feed_rate_mm_min, max_depth_mm)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (t["tool_number"], t["tool_name"], t["tool_type"], t["diameter_mm"],
              t["default_spindle_rpm"], t["default_feed_rate_mm_min"], t["max_depth_mm"]))
    conn.commit()
    conn.close()


def load_tools_from_db():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM tools ORDER BY tool_number", conn)
    conn.close()
    if df.empty:
        return []
    return df.to_dict("records")


def save_features_to_db(features):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM features")
    for f in features:
        c.execute("""
            INSERT INTO features (feature_name, feature_type, quantity, x_pos, y_pos,
                diameter, length, width, depth, tolerance_note, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (f["feature_name"], f["feature_type"], f["quantity"], f["x_pos"], f["y_pos"],
              f["diameter"], f["length"], f["width"], f["depth"], f["tolerance_note"], f["priority"]))
    conn.commit()
    conn.close()


def load_features_from_db():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM features ORDER BY priority", conn)
    conn.close()
    if df.empty:
        return []
    return df.to_dict("records")


def add_job_note(stage: str, author: str, note_type: str, note: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO job_notes (timestamp, stage, author, note_type, note) VALUES (?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), stage, author, note_type, note),
    )
    conn.commit()
    conn.close()


def load_job_notes():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM job_notes ORDER BY id DESC", conn)
    conn.close()
    if df.empty:
        return []
    return df.to_dict("records")


def delete_job_note(note_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM job_notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()


def clear_all_job_notes():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM job_notes")
    conn.commit()
    conn.close()


init_db()
