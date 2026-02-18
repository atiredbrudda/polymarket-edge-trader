#!/bin/sh
# Install git hooks for the project
# Run once after cloning: bash scripts/install-hooks.sh

HOOK_DIR="$(git rev-parse --show-toplevel)/.git/hooks"

cat > "$HOOK_DIR/pre-commit" << 'EOF'
#!/bin/sh

# Block direct commits to main
branch=$(git symbolic-ref --short HEAD 2>/dev/null)
if [ "$branch" = "main" ]; then
    echo ""
    echo "ERROR: Direct commits to main are blocked."
    echo "Create a feature branch first: git checkout -b worker/<name>"
    echo ""
    echo "If you REALLY need to commit to main, use: git commit --no-verify"
    exit 1
fi

# Check ruff formatting on staged Python files
STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' || true)
if [ -n "$STAGED_PY" ]; then
    if command -v ruff >/dev/null 2>&1; then
        if ! ruff format --check $STAGED_PY 2>/dev/null; then
            echo ""
            echo "ERROR: Unformatted Python files detected."
            echo "Run: ruff format src/ tests/"
            echo ""
            exit 1
        fi
        if ! ruff check $STAGED_PY 2>/dev/null; then
            echo ""
            echo "ERROR: Lint issues found."
            echo "Run: ruff check --fix src/ tests/"
            echo ""
            exit 1
        fi
    fi
fi
EOF

chmod +x "$HOOK_DIR/pre-commit"
echo "Pre-commit hook installed successfully."
