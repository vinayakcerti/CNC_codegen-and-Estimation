"""Regression checks for SQLite storage failure recovery."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import modules.data_store as data_store


def main():
    invalid_database_path = _PROJECT_ROOT / "modules"
    fallback_path = data_store._fallback_db_path().with_name(
        "cnc_planner_failover_regression.db"
    )
    fallback_path.unlink(missing_ok=True)

    original_path = data_store.DB_PATH
    original_override = data_store._DB_PATH_OVERRIDDEN
    original_fallback = data_store._fallback_db_path
    try:
        data_store.DB_PATH = invalid_database_path
        data_store._DB_PATH_OVERRIDDEN = False
        data_store._fallback_db_path = lambda: fallback_path
        data_store.init_db()

        assert data_store.DB_PATH == fallback_path
        assert fallback_path.exists()
        status = data_store.get_database_status()
        assert status["available"] is True
        assert status["path"] == str(fallback_path)
        assert "using fallback" in (status.get("migration_error") or "")

        defaults = data_store.get_default_tools()
        data_store.save_tools_to_db(defaults)
        loaded = data_store.load_tools_from_db()
        assert len(loaded) == len(defaults)
        assert any(tool.get("diameter_mm") == 8.0 for tool in loaded)
    finally:
        data_store.DB_PATH = original_path
        data_store._DB_PATH_OVERRIDDEN = original_override
        data_store._fallback_db_path = original_fallback
        fallback_path.unlink(missing_ok=True)

    print("PASS: database storage failure switches to writable fallback")


if __name__ == "__main__":
    main()
