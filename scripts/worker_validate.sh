#!/bin/bash
# === Worker Pre-Submit Validation ===
# Run from repo root on your feature branch.
# Every check must pass before you push.
#
# Usage: bash scripts/worker_validate.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

BRANCH=$(git branch --show-current)
if [ "$BRANCH" = "main" ]; then
    echo -e "${RED}FATAL: You are on main. Switch to a feature branch.${NC}"
    exit 1
fi

echo "Validating branch: $BRANCH"
echo "========================================="
echo ""

FAILURES=0

# --- CHECK 1: Cosmetic reformatting ---
echo "=== CHECK 1: Diff size (cosmetic reformatting?) ==="
CHANGED=$(git diff main..HEAD -- 'src/' ':(exclude)*.md' | grep "^[+-]" | grep -v "^[+-][+-][+-]" | wc -l | tr -d ' ')
echo "  Lines changed in src/: $CHANGED"
if [ "$CHANGED" -gt 500 ]; then
    echo -e "  ${YELLOW}WARNING: High line count. Verify you didn't reformat unrelated code.${NC}"
    echo "  RULE 1: Only modify lines directly required by your task."
fi
echo ""

# --- CHECK 2: Test regressions ---
echo "=== CHECK 2: Test regressions ==="
echo "  Running full test suite..."
RESULT=$(python -m pytest tests/ -q --tb=no 2>&1 | tail -1)
echo "  Result: $RESULT"

# Extract failure count
FAIL_COUNT=$(echo "$RESULT" | grep -oP '\d+ failed' | grep -oP '\d+' || echo "0")
# Main baseline (update this after each merge to main)
MAIN_FAILURES=9
if [ "$FAIL_COUNT" -gt "$MAIN_FAILURES" ]; then
    REGRESSIONS=$((FAIL_COUNT - MAIN_FAILURES))
    echo -e "  ${RED}FAIL: $REGRESSIONS new test regressions (main has $MAIN_FAILURES failures, you have $FAIL_COUNT).${NC}"
    echo "  Fix these before submitting. Run: pytest tests/ -x --tb=short"
    FAILURES=$((FAILURES + 1))
else
    echo -e "  ${GREEN}OK: No new regressions.${NC}"
fi
echo ""

# --- CHECK 3: Debug hardcodes ---
echo "=== CHECK 3: Debug hardcodes ==="
FOUND=$(git diff main..HEAD -- 'src/' | grep -iP "^\+" | grep -iP "TODO|hardcode|temporary|FIXME" | grep -v "^+++" | head -10)
if [ -n "$FOUND" ]; then
    echo -e "  ${YELLOW}WARNING: Potential debug artifacts in diff:${NC}"
    echo "$FOUND"
else
    echo -e "  ${GREEN}Clean.${NC}"
fi
echo ""

# --- CHECK 4: Changed functions → test coverage ---
echo "=== CHECK 4: Changed functions → test coverage ==="
echo "  Functions you added/modified:"
FUNCS=$(git diff main..HEAD -- 'src/' | grep "^+.*def " | sed 's/^+/  /' | head -20)
if [ -n "$FUNCS" ]; then
    echo "$FUNCS"
    echo ""
    echo "  For each function above, verify tests exist:"
    echo "    grep -r 'function_name' tests/"
else
    echo "  (none)"
fi
echo ""

# --- CHECK 5: Branch protection ---
echo "=== CHECK 5: Branch protection ==="
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
    echo -e "  ${RED}FAIL: Cannot submit from main/master branch.${NC}"
    FAILURES=$((FAILURES + 1))
else
    echo -e "  ${GREEN}OK: On feature branch '$BRANCH'.${NC}"
fi
echo ""

# --- SUMMARY ---
echo "========================================="
if [ "$FAILURES" -gt 0 ]; then
    echo -e "${RED}VALIDATION FAILED: $FAILURES check(s) failed. Fix issues before submitting.${NC}"
    exit 1
else
    echo -e "${GREEN}VALIDATION PASSED. Update REVIEW_QUEUE.md and push.${NC}"
fi
