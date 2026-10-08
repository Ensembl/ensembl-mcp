import os
import subprocess
import sys

import pytest

from ensembl_mcp.config import ConfigurationError, Settings


@pytest.mark.parametrize("endpoint", [
    None, "", "   ", "not-a-url", "ftp://host/path", "http:///path",
    "http://host:bad", "http://host:65536", "http://host:0", "http://[bad",
    "https://user:secret@host", "http://host/#fragment", "http://has space/",
    "http://host/\npath",
])
def test_invalid_endpoint(endpoint):
    env = {} if endpoint is None else {"ENSEMBL_CORE_GRAPHQL_URL": endpoint}
    with pytest.raises(ConfigurationError, match="ENSEMBL_CORE_GRAPHQL_URL") as exc:
        Settings.from_env(env)
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("timeout", ["", "abc", "0", "-1", "nan", "inf", "-inf"])
def test_invalid_timeout(timeout):
    with pytest.raises(ConfigurationError, match="TIMEOUT_SECONDS"):
        Settings.from_env({
            "ENSEMBL_CORE_GRAPHQL_URL": "https://example.invalid/graphql",
            "ENSEMBL_CORE_GRAPHQL_TIMEOUT_SECONDS": timeout,
        })


def test_configuration_defaults_and_overrides():
    config = Settings.from_env({"ENSEMBL_CORE_GRAPHQL_URL": " https://example.invalid/graphql "})
    assert config.endpoint == "https://example.invalid/graphql"
    assert config.mcp_transport == "stdio"
    assert config.mcp_port == 8000
    assert config.http_timeout.connect == 5
    assert config.http_timeout.read == 30
    assert config.http_timeout.write == 30
    assert config.http_timeout.pool == 30
    custom = Settings.from_env({
        "ENSEMBL_CORE_GRAPHQL_URL": "http://localhost:8000",
        "ENSEMBL_CORE_GRAPHQL_TIMEOUT_SECONDS": "45.5",
    })
    assert custom.http_timeout.read == custom.http_timeout.write == custom.http_timeout.pool == 45.5
    assert custom.http_timeout.connect == 5


@pytest.mark.parametrize("port", ["", "abc", "0", "-1", "65536", "8000.5", "inf"])
def test_invalid_mcp_port(port):
    with pytest.raises(ConfigurationError, match="MCP_PORT"):
        Settings.from_env({"ENSEMBL_CORE_GRAPHQL_URL": "http://example.invalid", "MCP_PORT": port})


@pytest.mark.parametrize("transport", ["", "http", "sse", "unknown"])
def test_invalid_mcp_transport(transport):
    with pytest.raises(ConfigurationError, match="MCP_TRANSPORT"):
        Settings.from_env({
            "ENSEMBL_CORE_GRAPHQL_URL": "http://example.invalid", "MCP_TRANSPORT": transport,
        })


def test_http_configuration():
    settings = Settings.from_env({
        "ENSEMBL_CORE_GRAPHQL_URL": "http://example.invalid",
        "MCP_TRANSPORT": "streamable-http", "MCP_PORT": "8080",
    })
    assert settings.mcp_transport == "streamable-http"
    assert settings.mcp_port == 8080


def test_startup_configuration_error_is_stderr_only():
    env = {key: value for key, value in os.environ.items() if not key.startswith("ENSEMBL_CORE_GRAPHQL_")}
    result = subprocess.run(
        [sys.executable, "-m", "ensembl_mcp.server"], env=env,
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "ENSEMBL_CORE_GRAPHQL_URL is required" in result.stderr
    assert "Traceback" not in result.stderr
