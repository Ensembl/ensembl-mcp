FROM node:22-trixie-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Alpine 3.24 still ships SQLite 3.53.4. Build the upstream security release
# without adding an edge repository; preserve the version in the APK inventory.
FROM python:3.12-alpine3.24 AS sqlite
RUN apk add --no-cache build-base
ADD --checksum=sha256:926ef8d3eab93fbf6e06011901273eec076b25594a4e1cdadd50c987f4f6d64e \
    https://sqlite.org/2026/sqlite-autoconf-3540100.tar.gz /tmp/sqlite.tar.gz
RUN mkdir -p /build /package/usr/lib \
    && tar -xzf /tmp/sqlite.tar.gz -C /build --strip-components=1 \
    && cc -O2 -fPIC -shared -pthread -DSQLITE_THREADSAFE=1 \
        -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_ENABLE_RTREE \
        -Wl,-soname,libsqlite3.so.0 -o /package/usr/lib/libsqlite3.so.0 /build/sqlite3.c -lm \
    && apk mkpkg --files /package --output /tmp/sqlite-libs.apk \
        --info name:sqlite-libs --info version:3.54.1-r0 --info origin:sqlite \
        --info "arch:$(apk --print-arch)" --info license:blessing \
        --info url:https://sqlite.org --info "description:SQLite upstream security release" \
        --info depends:musl --info provides:so:libsqlite3.so.0=0

FROM python:3.12-alpine3.24

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MCP_TRANSPORT=streamable-http \
    MCP_PORT=8000

WORKDIR /app

COPY pyproject.toml requirements.lock setup.py README.md LICENSE ./
COPY src/ensembl_mcp/ ./src/ensembl_mcp/
COPY --from=frontend /app/src/ensembl_mcp/ui/ ./src/ensembl_mcp/ui/
COPY --from=sqlite /tmp/sqlite-libs.apk /tmp/sqlite-libs.apk

RUN apk upgrade --no-cache \
    && apk add --no-network --allow-untrusted /tmp/sqlite-libs.apk \
    && rm /tmp/sqlite-libs.apk \
    && python -m pip install --upgrade pip==26.3 \
    && python -m pip install --require-hashes -r requirements.lock \
    && python -m pip install --no-deps . \
    && python -m pip uninstall -y setuptools pip \
    && python -c "import pathlib, shutil, sysconfig; shutil.rmtree(pathlib.Path(sysconfig.get_path('stdlib')) / 'ensurepip')" \
    && python -c "import sqlite3; c = sqlite3.connect(':memory:'); c.execute('create virtual table f using fts5(value)'); c.execute('insert into f values (?)', ('security',)); c.execute(\"select * from f where f match 'security'\").fetchone(); print('SQLite', sqlite3.sqlite_version); exit(0 if sqlite3.sqlite_version_info >= (3, 54, 1) else 1)" \
    && addgroup -g 10001 ensembl \
    && adduser -D -u 10001 -G ensembl ensembl \
    && find / -xdev -type f \( -perm -4000 -o -perm -2000 \) -exec chmod a-s '{}' +

USER ensembl

# Default Streamable HTTP port; override MCP_PORT and the port mapping together.
EXPOSE 8000
CMD ["ensembl-mcp"]
