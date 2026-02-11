"""Alert detection and delivery system.

Provides signal event detection, change tracking, and notification delivery.
"""

__all__ = []

try:
    from src.alerts.detector import detect_signal_event

    __all__.append("detect_signal_event")
except ImportError:
    pass

try:
    from src.alerts.formatter import format_signal_alert, get_expert_position_details

    __all__.extend(["format_signal_alert", "get_expert_position_details"])
except ImportError:
    pass

try:
    from src.alerts.telegram import TelegramAlerter

    __all__.append("TelegramAlerter")
except ImportError:
    pass

try:
    from src.alerts.delivery import deliver_signal_alerts, AlertDeliveryResult, AlertDeduplicator

    __all__.extend(["deliver_signal_alerts", "AlertDeliveryResult", "AlertDeduplicator"])
except ImportError:
    pass
