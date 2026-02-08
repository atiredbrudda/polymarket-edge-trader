"""Alert detection and delivery system.

Provides signal event detection, change tracking, and notification delivery.
"""

try:
    from src.alerts.detector import detect_signal_event

    __all__ = ["detect_signal_event"]
except ImportError:
    # Module not yet implemented - allows parallel plan execution
    __all__ = []
