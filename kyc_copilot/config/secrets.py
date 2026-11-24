"""Spec-aligned alias module exporting Mudra Secret Manager utilities."""

from kyc_copilot.config.mudra_secrets import (
    MudraSecretVault,
    fetch_secret,
    get_mudra_vault,
)

__all__ = ["MudraSecretVault", "fetch_secret", "get_mudra_vault"]
