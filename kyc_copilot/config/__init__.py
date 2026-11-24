"""Mudra Secret Manager configuration package."""

from kyc_copilot.config.mudra_secrets import MudraSecretVault, fetch_secret

__all__ = ["MudraSecretVault", "fetch_secret"]
