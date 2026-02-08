---
phase: 06-alerting-system
plan: 02
subsystem: alerts
tags: [formatter, telegram, html, tdd]
dependency_graph:
  requires: [signals.pipeline.SignalResult, db.models.Position]
  provides: [alerts.formatter.format_signal_alert, alerts.formatter.get_expert_position_details]
  affects: []
tech_stack:
  added: [html.escape]
  patterns: [pure-functions, telegram-html, address-truncation]
key_files:
  created: [src/alerts/formatter.py, tests/test_alert_formatter.py]
  modified: []
decisions: []
metrics:
  duration_minutes: 3.83
  test_count: 16
  completed_date: 2026-02-08
---

# Phase 06 Plan 02: Alert Formatter Summary

**One-liner:** Telegram HTML formatter with event headers, HTML escaping, address truncation, and position details

## What Was Built

Implemented Telegram HTML alert formatting that transforms SignalResult data into rich, scannable push notifications.

**Core Functions:**
1. `format_signal_alert()` - Main formatting function
   - Event type headers (NEW, STRENGTHENING, WEAKENING, LOST)
   - HTML-escaped market questions
   - Signal metrics (direction, confidence, expert count, agreement %)
   - First mover and fast follower metadata
   - Expert addresses (first 5 with +N more)
   - Position sizes when provided
   - Polymarket link

2. `get_expert_position_details()` - Database query helper
   - Queries Position table for expert addresses
   - Returns dict format: address, size, direction, avg_entry_price

3. `_truncate_address()` - Address formatter
   - Truncates 42-char addresses to first 10 + ... + last 6

**Key Design Decisions:**
- Pure function pattern for `format_signal_alert` (no DB access)
- Separate DB accessor function for testability
- HTML escaping via `html.escape()` for security
- Telegram HTML tags: `<b>`, `<code>`, `<a href>`
- Address truncation for readability (0xabcdef12...cdef12)
- First 5 experts shown with "+N more" indicator

## Test Coverage

**16 tests, 100% passing:**

1. Event type headers (4 tests)
   - NEW, STRENGTHENING, WEAKENING, LOST
   
2. HTML escaping (1 test)
   - Special characters (<, >, &) properly escaped
   
3. Expert address handling (2 tests)
   - All shown when ≤5 experts
   - First 5 + "+N more" when >5 experts
   
4. Optional sections (2 tests)
   - First mover section omitted when None
   - Position sizes omitted when not provided
   
5. Position details (1 test)
   - Sizes and directions shown when provided
   
6. Telegram HTML (1 test)
   - Valid tags: b, code, a href
   
7. Required metrics (1 test)
   - Direction, confidence, expert count, agreement %
   
8. Follower classification (1 test)
   - Fast follower count from classifications
   
9. Database helper (3 tests)
   - Returns position details for experts
   - Empty list when no positions
   - Handles None avg_entry_price

**Full suite:** 390 tests passing (362 pre-Phase 6 + 16 formatter + 12 from 06-01)

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

```bash
.venv/bin/python -m pytest tests/test_alert_formatter.py -v
# 16 passed in 0.25s

.venv/bin/python -m pytest --tb=short -q
# 390 passed, 2449 warnings in 17.84s
```

All success criteria met:
- ✅ format_signal_alert produces valid Telegram HTML for all 4 event types
- ✅ All user-generated content properly HTML-escaped (no injection)
- ✅ Extended details: first-mover, fast-follower count, expert addresses, position sizes
- ✅ Addresses properly truncated for readability
- ✅ Output is scannable at a glance
- ✅ All tests pass including full regression suite

## Integration Points

**Inputs:**
- `SignalResult` dataclass from `src.signals.pipeline`
- Optional position details from `get_expert_position_details()`

**Outputs:**
- Telegram HTML string (parse_mode="HTML")
- Ready for Phase 06-03 (Telegram Bot Integration)

**Database Dependencies:**
- Position table query for expert position details
- Uses existing SQLAlchemy session pattern

## Performance

- Execution: 3.83 minutes
- TDD cycle: RED (1 commit) → GREEN (1 commit) → no refactor needed
- Pure functions enable fast unit testing (0.25s for 16 tests)

## Next Steps

Plan complete. Ready for Phase 06-03 (Telegram Bot Integration) which will:
- Use `format_signal_alert()` to create alert messages
- Send formatted HTML to Telegram via bot API
- Implement retry logic for delivery reliability

## Self-Check: PASSED

**Created files:**
- ✅ src/alerts/formatter.py exists (164 lines)
- ✅ tests/test_alert_formatter.py exists (301 lines)

**Commits:**
- ✅ 1ff3434 exists (test commit - RED phase)
- ✅ 6274c1f exists (feat commit - GREEN phase)

All files created, all tests passing, implementation complete.
