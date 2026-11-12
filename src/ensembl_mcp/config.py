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
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]")
    allowed_origins: tuple[str, ...] = ()
    max_concurrent_requests: int = 16
    requests_per_minute: int = 120
    max_request_bytes: int = 65_536
    request_timeout_seconds: float = 30.0
    max_concurrent_tools: int = 8
    tool_timeout_seconds: float = 20.0
    search_url: str = field(kw_only=True)
    metadata_url: str | None = None
    tracks_url: str | None = None
    browser_backend_url: str = "https://mcp-poc-public.review.ensembl.org/api/browser/data"
    browser_website_url: str = "https://mcp-poc-public.review.ensembl.org"
    browser_genome_ids: tuple[str, ...] = ("59871324-7803-4234-856e-2a2bd96d7b3c",)

    def __post_init__(self) -> None:
        if self.mcp_transport not in {"stdio", "streamable-http"}:
            raise ConfigurationError("MCP_TRANSPORT must be stdio or streamable-http.")
        if type(self.mcp_port) is not int or not 1 <= self.mcp_port <= 65535:
            raise ConfigurationError("MCP_PORT must be an integer between 1 and 65535.")
        for name in ("max_concurrent_requests", "requests_per_minute", "max_request_bytes", "max_concurrent_tools"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ConfigurationError(f"MCP_{name.upper()} must be a positive integer.")
        for name in ("request_timeout_seconds", "tool_timeout_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ConfigurationError(f"MCP_{name.upper()} must be finite and positive.")
        if not self.allowed_hosts:
            raise ConfigurationError("MCP_ALLOWED_HOSTS must contain explicit hostnames.")
        for host in self.allowed_hosts:
            try:
                parsed = urlsplit("//" + host)
                valid = (parsed.hostname and parsed.netloc == host and parsed.port is None
                         and not parsed.username and not parsed.password and "*" not in host
                         and not any(c.isspace() or ord(c) < 32 for c in host))
            except ValueError:
                valid = False
            if not valid:
                raise ConfigurationError("MCP_ALLOWED_HOSTS must contain hostnames without ports, wildcards or URLs.")
        for origin in self.allowed_origins:
            try:
                parsed = urlsplit(origin)
                valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                         and origin == f"{parsed.scheme}://{parsed.netloc}"
                         and not parsed.username and not parsed.password and "*" not in origin
                         and (parsed.port is None or 0 < parsed.port <= 65535)
                         and not any(c.isspace() or ord(c) < 32 for c in origin))
            except ValueError:
                valid = False
            if not valid:
                raise ConfigurationError("MCP_ALLOWED_ORIGINS must contain exact HTTP(S) origins without paths or wildcards.")
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
        for name, value in (
            ("ENSEMBL_GENOME_SEARCH_URL", self.search_url),
            ("ENSEMBL_METADATA_API_URL", self.metadata_url),
            ("ENSEMBL_TRACKS_API_URL", self.tracks_url),
            ("ENSEMBL_BROWSER_BACKEND_URL", self.browser_backend_url),
            ("ENSEMBL_BROWSER_WEBSITE_URL", self.browser_website_url),
        ):
            if value is None and name in {"ENSEMBL_METADATA_API_URL", "ENSEMBL_TRACKS_API_URL"}:
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
            if name.startswith("ENSEMBL_BROWSER_") and url.scheme != "https":
                raise ConfigurationError(f"{name} must use HTTPS for the sandboxed app.")
        if self.browser_backend_url.rstrip("/").endswith(("/hi", "/lo")):
            raise ConfigurationError("ENSEMBL_BROWSER_BACKEND_URL must omit the hi/lo priority suffix.")
        from uuid import UUID
        try:
            if not self.browser_genome_ids:
                raise ValueError
            for genome_id in self.browser_genome_ids:
                if str(UUID(genome_id)) != genome_id:
                    raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ConfigurationError("ENSEMBL_BROWSER_GENOME_IDS must contain comma-separated canonical genome UUIDs.") from None

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
        limits = {}
        for name in ("max_concurrent_requests", "requests_per_minute", "max_request_bytes",
                     "max_concurrent_tools", "request_timeout_seconds", "tool_timeout_seconds"):
            try:
                convert = float if name.endswith("seconds") else int
                limits[name] = convert(env.get(f"MCP_{name.upper()}", str(getattr(cls, name))))
            except ValueError:
                raise ConfigurationError(f"MCP_{name.upper()} must be a valid positive number.") from None
        return cls(
            endpoint, timeout,
            mcp_transport=env.get("MCP_TRANSPORT", "stdio").strip(),
            mcp_port=port,
            allowed_hosts=tuple(value.strip().lower() for value in env.get(
                "MCP_ALLOWED_HOSTS", ",".join(cls.allowed_hosts)
            ).split(",")),
            allowed_origins=tuple(value.strip() for value in env.get(
                "MCP_ALLOWED_ORIGINS", ""
            ).split(",") if value.strip()),
            **limits,
            search_url=search_url,
            metadata_url=env.get("ENSEMBL_METADATA_API_URL", "").strip() or None,
            tracks_url=env.get("ENSEMBL_TRACKS_API_URL", "").strip() or None,
            browser_backend_url=env.get("ENSEMBL_BROWSER_BACKEND_URL", cls.browser_backend_url).strip(),
            browser_website_url=env.get("ENSEMBL_BROWSER_WEBSITE_URL", cls.browser_website_url).strip(),
            browser_genome_ids=tuple(value.strip() for value in env.get(
                "ENSEMBL_BROWSER_GENOME_IDS", ",".join(cls.browser_genome_ids)
            ).split(",")),
        )

    @property
    def http_timeout(self) -> httpx.Timeout:
        # HTTPX limits inactivity per phase, not total wall-clock duration.
        return httpx.Timeout(self.timeout_seconds, connect=5.0)
