"""Detection & diagnosis layer: anti-bot vendors, fingerprint coherence, behavior."""

from .antibot import detect_antibot, detect_from_html, detect_vendors
from .behavioral import analyze_behavior
from .fingerprint import fingerprint_report, fp_signals

__all__ = [
    "analyze_behavior",
    "detect_antibot",
    "detect_from_html",
    "detect_vendors",
    "fingerprint_report",
    "fp_signals",
]
