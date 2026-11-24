"""Kavach Active PII Redaction Pipeline (Google Cloud DLP + Regex Fallback).

Named after *Kavach* (protective armor in Indian epics), this module actively
scrubs Personally Identifiable Information (PII) before any structured log line
or persistent memory record is written. Uses Google Cloud DLP when enabled in
GCP, paired with a deterministic regex/key-aware scrubber for zero-dependency
local and CI enforcement.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Sensitive dictionary keys whose entire string values are masked on write.
SENSITIVE_KEY_TOKENS: dict[str, str] = {
    "dob": "[REDACTED_DOB]",
    "date_of_birth": "[REDACTED_DOB]",
    "mentioned_dob": "[REDACTED_DOB]",
    "residential_address": "[REDACTED_ADDRESS]",
    "home_address": "[REDACTED_ADDRESS]",
    "passport": "[REDACTED_PASSPORT]",
    "passport_number": "[REDACTED_PASSPORT]",
    "nino": "[REDACTED_TAX_ID]",
    "ssn": "[REDACTED_TAX_ID]",
    "iban": "[REDACTED_IBAN]",
    "email": "[REDACTED_EMAIL]",
}

# Ordered deterministic regex rules (specific patterns first).
_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # International Bank Account Numbers (IBAN, e.g., GB29NWBK60161331926819)
    (
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
        "[REDACTED_IBAN]",
    ),
    # Email addresses
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    # UK National Insurance Number (real HMRC prefixes + official test prefix QQ, e.g., QQ123456C)
    (
        re.compile(r"\b(?:NINo\s+)?[A-Z]{2}\s?\d{6}\s?[A-D]\b"),
        "[REDACTED_TAX_ID]",
    ),
    # US Social Security Number (e.g., 123-45-6789)
    (
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "[REDACTED_TAX_ID]",
    ),
    # Passport numbers (e.g., AB1234567 or labeled Passport AB1234567)
    (
        re.compile(r"\b(?:Passport\s*#?\s*)?[A-Z]{2}\d{7}\b"),
        "[REDACTED_PASSPORT]",
    ),
    # Human Dates of Birth (1900-2019 YYYY-MM-DD not followed by ISO 'T')
    (
        re.compile(r"\b(?:DOB[:\s]+)?(?:19\d{2}|20[01]\d)-\d{2}-\d{2}\b(?!T)"),
        "[REDACTED_DOB]",
    ),
    # Personal street / villa addresses in free text
    (
        re.compile(
            r"\b(?:Villa\s+\d+,\s*[^,;]+|\d{1,4}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\s+"
            r"(?:Road|Street|Avenue|Lane|Place|Hill|Way|Drive|Close|Terrace))\b"
        ),
        "[REDACTED_ADDRESS]",
    ),
]


class KavachPiiRedactor:
    """Dual-mode active PII scrubber (Cloud DLP API + deterministic regex)."""

    def __init__(
        self,
        enable_cloud_dlp: bool | None = None,
        project_id: str | None = None,
    ) -> None:
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
        if enable_cloud_dlp is None:
            self.enable_cloud_dlp = (
                os.getenv("ENABLE_CLOUD_DLP", "false").lower() == "true"
            )
        else:
            self.enable_cloud_dlp = enable_cloud_dlp

    def _scrub_with_cloud_dlp(self, text: str) -> str:
        """Invokes Google Cloud DLP deidentify_content when enabled on GCP."""
        if not (self.enable_cloud_dlp and self.project_id and text.strip()):
            return text
        try:
            from google.cloud import dlp_v2

            dlp_client = dlp_v2.DlpServiceClient()
            parent = f"projects/{self.project_id}/locations/global"
            inspect_config = {
                "info_types": [
                    {"name": "PASSPORT"},
                    {"name": "UK_NATIONAL_INSURANCE_NUMBER"},
                    {"name": "US_SOCIAL_SECURITY_NUMBER"},
                    {"name": "DATE_OF_BIRTH"},
                    {"name": "EMAIL_ADDRESS"},
                    {"name": "IBAN_CODE"},
                    {"name": "STREET_ADDRESS"},
                ]
            }
            deidentify_config = {
                "info_type_transformations": {
                    "transformations": [
                        {
                            "primitive_transformation": {
                                "replace_with_info_type_config": {}
                            }
                        }
                    ]
                }
            }
            response = dlp_client.deidentify_content(
                request={
                    "parent": parent,
                    "inspect_config": inspect_config,
                    "deidentify_config": deidentify_config,
                    "item": {"value": text},
                }
            )
            return response.item.value
        except Exception:
            # Always fall back cleanly to deterministic regex redaction.
            return text

    def redact_text(self, text: str) -> str:
        """Actively scrubs PII from a plain text string."""
        cleaned = self._scrub_with_cloud_dlp(text)
        for pattern, replacement in _PII_PATTERNS:
            cleaned = pattern.sub(replacement, cleaned)
        return cleaned

    def redact_value(self, value: Any, key_hint: str | None = None) -> Any:
        """Recursively scrubs PII across dicts, lists, and scalar values."""
        if key_hint:
            normalized_key = key_hint.lower()
            if normalized_key in SENSITIVE_KEY_TOKENS and value is not None:
                return SENSITIVE_KEY_TOKENS[normalized_key]

        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {
                k: self.redact_value(v, key_hint=str(k))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact_value(item) for item in value)
        return value


_DEFAULT_KAVACH_REDACTOR = KavachPiiRedactor()


def redact_pii(text: str) -> str:
    """Redacts sensitive PII tokens from text using the default Kavach scrubber."""
    return _DEFAULT_KAVACH_REDACTOR.redact_text(text)


def redact_pii_in_structure(payload: Any) -> Any:
    """Recursively redacts sensitive PII tokens across nested dicts and lists."""
    return _DEFAULT_KAVACH_REDACTOR.redact_value(payload)
