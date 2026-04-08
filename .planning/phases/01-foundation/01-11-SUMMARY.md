---
phase: 01-foundation
plan: 11
subsystem: database
tags: [sqlite, schema, numeric-affinity, signals]

requires:
  - phase: 01-foundation
    provides: signals table with float avg_score (01-01)
  - phase: 01-foundation
    provides: Raw SQL pattern for NUMERIC affinity (01-09)
provides:
  - signals.avg_score with NUMERIC(10,6) affinity via raw SQL
  - All 9 tables consistent — numeric columns use explicit NUMERIC affinity

key-files:
  modified:
    - src/polymarket_analytics/db/schema.py

key-decisions:
  - "Converted signals table to raw SQL db.execute() to match trades/positions/lift_scores pattern"

# Metrics
duration: 1 min
completed: 2026-03-29
---

# Phase 01: Plan 11: signals.avg_score NUMERIC Fix Summary

**Converted signals table to raw SQL with NUMERIC(10,6) on avg_score, completing schema consistency**

## Performance

- **Duration:** 1 min
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- signals table definition replaced from sqlite-utils .create() to db.execute() raw SQL
- avg_score now declared as NUMERIC(10,6) — consistent with trades.price, positions.avg_entry_price
- All 9 core tables now use raw SQL with explicit NUMERIC affinity for numeric columns

## Deviations from Plan

None.

---
*Phase: 01-foundation*
*Completed: 2026-03-29*
