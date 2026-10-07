"""Validate configuration before starting the MCP transport."""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class ConfigurationError(ValueError):
    """A safe startup message, without configuration values or credentials."""


@dataclass(frozen=True)
class Settings:
    endpoint: str
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        try:
            url = urlsplit(self.endpoint)
            valid = (
                url.scheme in {"http", "https"}
                and bool(url.hostname)
                and url.username is None
                and url.password is None
                and not url.fragment
                and not any(c.isspace() or ord(c) < 32 for c in self.endpoint)
                and (url.port is None or 0 < url.port <= 65535)
                and bool(httpx.URL(self.endpoint).host)
            )
        except (ValueError, httpx.InvalidURL):
            valid = False
        if not valid:
            raise ConfigurationError(
                "ENSEMBL_CORE_GRAPHQL_URL must be an absolute HTTP(S) URL "
                "with a host, no credentials, whitespace or fragment."
            )
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ConfigurationError(
                "ENSEMBL_CORE_GRAPHQL_TIMEOUT_SECONDS must be a finite positive number."
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        endpoint = env.get("ENSEMBL_CORE_GRAPHQL_URL", "").strip()
        if not endpoint:
            raise ConfigurationError("ENSEMBL_CORE_GRAPHQL_URL is required.")
        try:
            timeout = float(env.get("ENSEMBL_CORE_GRAPHQL_TIMEOUT_SECONDS", "30"))
        except ValueError:
            raise ConfigurationError(
                "ENSEMBL_CORE_GRAPHQL_TIMEOUT_SECONDS must be a finite positive number."
            ) from None
        return cls(endpoint, timeout)

    @property
    def http_timeout(self) -> httpx.Timeout:
        # HTTPX limits inactivity per phase, not total wall-clock duration.
        return httpx.Timeout(self.timeout_seconds, connect=5.0)
