#!/bin/bash
# Helper script to view CLI session logs in real-time

LOG_FILE="logs/cli_session.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "Log file not found: $LOG_FILE"
    echo "Run a polymarket command first to generate logs."
    exit 1
fi

case "${1:-tail}" in
    tail)
        echo "Following CLI logs (Ctrl+C to stop)..."
        tail -f "$LOG_FILE"
        ;;
    view)
        echo "Viewing entire log file..."
        cat "$LOG_FILE"
        ;;
    clear)
        echo "Clearing log file..."
        > "$LOG_FILE"
        echo "Log file cleared."
        ;;
    last)
        echo "Last 50 lines:"
        tail -n 50 "$LOG_FILE"
        ;;
    *)
        echo "Usage: $0 [tail|view|clear|last]"
        echo "  tail  - Follow logs in real-time (default)"
        echo "  view  - View entire log file"
        echo "  clear - Clear log file"
        echo "  last  - Show last 50 lines"
        exit 1
        ;;
esac
