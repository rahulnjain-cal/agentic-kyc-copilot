"""Mudra Secret Vault — Google Cloud Secret Manager with CI/Local Env Fallback.

Inspired by the royal *Mudra* (signet seal of authentication in Kautilya's
*Arthashastra*), this module centralizes secret retrieval so ZERO API keys or
credentials are ever hardcoded in source code or committed to Git.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional


class MudraSecretVault:
    """Fetches secrets from Google Cloud Secret Manager with graceful env fallback."""

    def __init__(
        self,
        project_id: Optional[str] = None,
        enable_secret_manager: Optional[bool] = None,
    ) -> None:
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
        if enable_secret_manager is None:
            self.enable_secret_manager = (
                os.getenv("ENABLE_SECRET_MANAGER", "false").lower() == "true"
            )
        else:
            self.enable_secret_manager = enable_secret_manager

    def get_secret(
        self,
        secret_name: str,
        env_fallback: Optional[str] = None,
        version: str = "latest",
    ) -> Optional[str]:
        """Retrieves a secret value from GCP Secret Manager or an env var.

        Args:
            secret_name: Secret resource name in Google Cloud Secret Manager.
            env_fallback: Optional environment variable name for local/CI runs.
            version: Secret Manager version identifier (defaults to "latest").

        Returns:
            The secret string if available, otherwise None.
        """
        if self.enable_secret_manager and self.project_id:
            try:
                from google.cloud import secretmanager

                client = secretmanager.SecretManagerServiceClient()
                resource_path = (
                    f"projects/{self.project_id}/secrets/{secret_name}"
                    f"/versions/{version}"
                )
                response = client.access_secret_version(
                    request={"name": resource_path}
                )
                return response.payload.data.decode("utf-8").strip()
            except Exception:
                # Fall back cleanly to environment variable in local/CI mode.
                pass

        if env_fallback:
            return os.getenv(env_fallback)
        return os.getenv(secret_name.upper().replace("-", "_"))


@lru_cache(maxsize=1)
def get_mudra_vault() -> MudraSecretVault:
    """Returns a cached singleton MudraSecretVault instance."""
    return MudraSecretVault()


def fetch_secret(
    secret_name: str,
    env_fallback: Optional[str] = None,
) -> Optional[str]:
    """Convenience helper to fetch a runtime secret without hardcoded keys."""
    return get_mudra_vault().get_secret(
        secret_name=secret_name,
        env_fallback=env_fallback,
    )
