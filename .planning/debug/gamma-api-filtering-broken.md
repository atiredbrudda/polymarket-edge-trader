---
status: resolved
trigger: "Gamma API tag and closed filters not working - tag=esports and closed=false returns non-esports markets with past end dates"
created: 2026-02-14T00:00:00Z
updated: 2026-02-14T00:15:00Z
---

## Current Focus

hypothesis: "Gamma API server-side filtering is broken AND category fallback is incorrectly applied"
test: "Verified API returns wrong markets regardless of tag filter"
expecting: "Need client-side filtering to validate results"
next_action: "Fix complete - client-side filtering implemented"

## Symptoms

expected: "Only esports markets closing within the specified timeframe should be returned"
actual: "3847 markets returned, many are Politics/Trump topics with past end dates, incorrectly labeled as Esports"
errors: "Gamma API filters (tag=esports, closed=false) not working - returns closed markets with past dates marked as active=True"
reproduction: "polymarket sweep --closing-within \"11hours\" --niche esports"
started: "Issue appeared after fixing conditionId field mapping"

## Eliminated

- hypothesis: "Filters not being passed to API correctly"
  evidence: "Verified params are correctly passed (closed=false, tag=esports)"
  timestamp: "2026-02-14T00:05:00Z"

## Evidence

- timestamp: "2026-02-14T00:05:00Z"
  checked: "Direct Gamma API call with tag=esports"
  found: "Returns Trump deportation markets regardless of tag filter - API server-side bug"
  implication: "Cannot rely on Gamma API server-side filtering"

- timestamp: "2026-02-14T00:06:00Z"
  checked: "Category fallback code in ingest.py"
  found: "Lines 315-317 incorrectly default category to niche when tags are missing"
  implication: "Non-esports markets get incorrectly labeled as Esports"

- timestamp: "2026-02-14T00:07:00Z"
  checked: "End date filtering"
  found: "Gamma API returns markets with endDate in past (2025-12-31) when closed=false"
  implication: "Need client-side filtering for endDate"

## Resolution

root_cause: "Gamma API server-side filtering is broken (returns wrong markets for any tag) + category fallback incorrectly labels markets"
fix: "Added client-side filtering via _filter_market_by_niche() function that validates: 1) market tags match requested niche, 2) endDate is valid, 3) removed problematic category fallback"
verification: "Syntax check passed, function logic tested in isolation"
files_changed:
  - src/pipeline/ingest.py
