"""Health log persistence — stores check results in health_log table."""
import json
from datetime import datetime, timezone


def create_health_log_table(db) -> None:
    """Create health_log table if not exists. Called from schema.py migrations."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS health_log (
            id TEXT PRIMARY KEY,
            tier TEXT,
            timestamp TEXT,
            status TEXT,
            checks TEXT,
            summary TEXT,
            niche TEXT
        )
    """)


def write_health_log(
    db, *, tier: str, status: str, checks: dict, summary: str, niche: str
) -> str:
    """Write one health_log row. Returns the row id (ISO timestamp)."""
    row_id = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT INTO health_log (id, tier, timestamp, status, checks, summary, niche) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [row_id, tier, row_id, status, json.dumps(checks), summary, niche],
    )
    db.conn.commit()
    return row_id


def read_health_log(
    db, *, tier: str | None = None, niche: str | None = None, limit: int = 10
) -> list[dict]:
    """Read health_log rows, optionally filtered by tier and/or niche."""
    query = "SELECT id, tier, timestamp, status, checks, summary, niche FROM health_log WHERE 1=1"
    params = []
    if tier:
        query += " AND tier = ?"
        params.append(tier)
    if niche:
        query += " AND niche = ?"
        params.append(niche)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(query, params).fetchall()
    return [
        {
            "id": r[0],
            "tier": r[1],
            "timestamp": r[2],
            "status": r[3],
            "checks": json.loads(r[4]) if r[4] else {},
            "summary": r[5],
            "niche": r[6],
        }
        for r in rows
    ]
