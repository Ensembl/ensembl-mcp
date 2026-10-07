FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ensembl_mcp/ ./src/ensembl_mcp/

RUN python -m pip install . \
    && useradd --create-home --uid 10001 --user-group ensembl

USER ensembl

# MCP uses stdin/stdout; no listening port is needed.
CMD ["ensembl-mcp"]
