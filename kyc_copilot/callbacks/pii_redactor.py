"""Spec-aligned alias module exporting Kavach active PII redaction utilities."""

from kyc_copilot.callbacks.kavach_pii_redactor import (
    KavachPiiRedactor,
    redact_pii,
    redact_pii_in_structure,
)

__all__ = [
    "KavachPiiRedactor",
    "redact_pii",
    "redact_pii_in_structure",
]
