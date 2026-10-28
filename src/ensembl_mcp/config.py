"""Validate configuration before starting the MCP transport."""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx


class ConfigurationError(ValueError):
    """A safe startup message, without configuration values or credentials."""


@dataclass(frozen=True)
class Settings:
    endpoint: str
    timeout_seconds: float = 30.0
    mcp_transport: str = "stdio"
    mcp_port: int = 8000
    search_url: str = field(kw_only=True)
    metadata_url: str | None = None

    def __post_init__(self) -> None:
        if self.mcp_transport not in {"stdio", "streamable-http"}:
            raise ConfigurationError("MCP_TRANSPORT must be stdio or streamable-http.")
        if type(self.mcp_port) is not int or not 1 <= self.mcp_port <= 65535:
            raise ConfigurationError("MCP_PORT must be an integer between 1 and 65535.")
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
        for name, value in (("ENSEMBL_GENOME_SEARCH_URL", self.search_url), ("ENSEMBL_METADATA_API_URL", self.metadata_url)):
            if value is None and name == "ENSEMBL_METADATA_API_URL":
                continue
            try:
                url = urlsplit(value)
                valid = (
                    url.scheme in {"http", "https"} and bool(url.hostname)
                    and url.username is None and url.password is None
                    and not url.fragment and not url.query
                    and not any(c.isspace() or ord(c) < 32 for c in value)
                    and (url.port is None or 0 < url.port <= 65535)
                    and bool(httpx.URL(value).host)
                )
            except (TypeError, ValueError, httpx.InvalidURL):
                valid = False
            if not valid:
                raise ConfigurationError(f"{name} must be an absolute HTTP(S) URL without credentials, query or fragment.")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        endpoint = env.get("ENSEMBL_CORE_GRAPHQL_URL", "").strip()
        if not endpoint:
            raise ConfigurationError("ENSEMBL_CORE_GRAPHQL_URL is required.")
        search_url = env.get("ENSEMBL_GENOME_SEARCH_URL", "").strip()
        if not search_url:
            raise ConfigurationError("ENSEMBL_GENOME_SEARCH_URL is required.")
        try:
            timeout = float(env.get("ENSEMBL_CORE_GRAPHQL_TIMEOUT_SECONDS", "30"))
        except ValueError:
            raise ConfigurationError(
                "ENSEMBL_CORE_GRAPHQL_TIMEOUT_SECONDS must be a finite positive number."
            ) from None
        try:
            port = int(env.get("MCP_PORT", "8000"))
        except ValueError:
            raise ConfigurationError("MCP_PORT must be an integer between 1 and 65535.") from None
        return cls(
            endpoint, timeout,
            mcp_transport=env.get("MCP_TRANSPORT", "stdio").strip(),
            mcp_port=port,
            search_url=search_url,
            metadata_url=env.get("ENSEMBL_METADATA_API_URL", "").strip() or None,
        )

    @property
    def http_timeout(self) -> httpx.Timeout:
        # HTTPX limits inactivity per phase, not total wall-clock duration.
        return httpx.Timeout(self.timeout_seconds, connect=5.0)
