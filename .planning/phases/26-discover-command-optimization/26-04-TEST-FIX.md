# Phase 26: Test Fix Summary

**Date:** 2026-03-23  
**Issue:** 3 failing tests in `tests/datasources/test_jbecker.py` discovered after full test suite run  
**Worker:** Fix applied to branch `worker/26-01-research`

---

## Problem Discovery

After completing Phase 26 implementation, ran the full test suite and found 3 pre-existing test failures:

```
tests/datasources/test_jbecker.py::test_query_uses_parameterized_sql FAILED
tests/datasources/test_jbecker.py::test_query_no_string_interpolation FAILED
tests/datasources/test_jbecker.py::test_query_market_trades_parameterized FAILED
```

### Root Cause

The tests were mocking the wrong DuckDB method:

**Tests expected:** `duckdb.execute()` (module-level function)  
**Code actually uses:** `duckdb.connect()` → `conn.execute()` (connection method)

The `JBeckerDataset._execute()` method at `src/datasources/jbecker.py:76` creates a connection:
```python
def _execute(self, query: str, params: list | None = None):
    conn = duckdb.connect(config={"threads": 2, "memory_limit": "3GB"})
    result = conn.execute(query, params or [])
    return result, conn
```

But the tests mocked `duckdb.execute` which doesn't exist — causing `mock_execute.call_args` to be `None`.

---

## Solution

Updated 3 test functions to mock the correct method:

| Test | Before | After |
|------|--------|-------|
| `test_query_uses_parameterized_sql` | `patch("duckdb.execute")` | `patch("duckdb.connect")` |
| `test_query_no_string_interpolation` | `patch("duckdb.execute")` | `patch("duckdb.connect")` |
| `test_query_market_trades_parameterized` | `patch("duckdb.execute")` | `patch("duckdb.connect")` |

### Changes Made

```diff
- with patch("duckdb.execute") as mock_execute:
+ with patch("duckdb.connect") as mock_connect:
+     mock_conn = MagicMock()
      mock_result = MagicMock()
      mock_result.fetchdf.return_value.to_dict.return_value = []
-     mock_execute.return_value = mock_result
+     mock_conn.execute.return_value = mock_result
+     mock_connect.return_value = mock_conn

      trader = "0x..."
      jbecker_dataset.query_trader_history(trader)

-     assert mock_execute.called
-     call_args = mock_execute.call_args
+     assert mock_conn.execute.called
+     call_args = mock_conn.execute.call_args
```

---

## Test Results

### Before Fix
```
FAILED tests/datasources/test_jbecker.py::test_query_uses_parameterized_sql
FAILED tests/datasources/test_jbecker.py::test_query_no_string_interpolation
FAILED tests/datasources/test_jbecker.py::test_query_market_trades_parameterized
3 failed, 21 passed
```

### After Fix
```
tests/datasources/test_jbecker.py::test_query_uses_parameterized_sql PASSED
tests/datasources/test_jbecker.py::test_query_no_string_interpolation PASSED
tests/datasources/test_jbecker.py::test_query_market_trades_parameterized PASSED
24 passed in 0.56s
```

### Full Datasource Tests
```
38 passed in 0.52s
```

### Core Module Tests
```
tests/datasources/ tests/extraction/ tests/blockchain/: 72 passed
```

---

## Commit

**Branch:** `worker/26-01-research`  
**Commit:** `77560e9`  
**Message:**
```
fix: update jbecker tests to mock duckdb.connect instead of duckdb.execute

The code uses duckdb.connect() then conn.execute(), so tests need to mock
the connection's execute method, not the module-level execute function.

This fixes 3 failing tests:
- test_query_uses_parameterized_sql
- test_query_no_string_interpolation
- test_query_market_trades_parameterized
```

---

## Full Test Suite Status

**Note:** The full test suite (`pytest tests/`) has pre-existing failures unrelated to this fix:

- `tests/test_alert_delivery.py`: 5 failures (alert sending logic)
- `tests/test_catalog_builder.py`: 4 failures (market classification)
- `tests/test_alert_formatter.py`: 13 errors (Telegram formatting)

These failures existed before Phase 26 and are not caused by the changes in this phase.

**Phase 26 specific tests:** All passing ✓

---

## Lesson Learned

When mocking database calls, always verify the actual call stack:
1. Check if code uses module-level functions vs instance methods
2. Mock the actual object that receives the call
3. For connection pools or factory patterns, mock the factory and verify calls on the returned connection

This test suite was written assuming `duckdb.execute()` existed (like some DB APIs), but DuckDB uses `duckdb.connect()` → `conn.execute()` pattern.

---

## Files Changed

| File | Lines Changed | Type |
|------|---------------|------|
| `tests/datasources/test_jbecker.py` | +16, -11 | Test fix |

No production code was modified — only test mocking strategy.

---

**Status:** ✅ Complete  
**Ready for:** Reviewer approval and merge to main
