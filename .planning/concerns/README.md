# Concerns

## Sell-Only Open Positions Issue
- **Status**: Still persists
- **History**: First fixed and merged in branch `worker/fix-graph-buy-ingestion`
- **Evidence**: Sanity check on 07/04/2026 18:07 shows sell-only open positions
- **Action**: Investigate and fix the root cause

## Deduction Problem (Duplicate Records)
- **Question**: Is the duplicate records problem fully solved?
- **Action**: Verify current deduplication logic and test coverage

## Backfill Performance
- **Observation**: Last backfill took ~2 hours for only 247 trader records
- **Question**: Why did it take so long?
- **Action**: Profile backfill process, identify bottlenecks

## Deduplication Strategy
- **Question**: Clarify the duplication handling that happens:
  - Pre-backfill
  - Post-backfill
- **Action**: Document how deduplication works in both phases and verify effectiveness
