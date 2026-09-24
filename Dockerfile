ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.1@sha256:fc93e9ecd7218e9ec8fba117af89348eef8fd2463c50c13347478769aaedd0ce
ARG PYTHON_IMAGE=python:3.12.7-slim@sha256:60d9996b6a8a3689d36db740b49f4327be3be09a21122bd02fb8895abb38b50d
ARG NODE_IMAGE=node:22-alpine
FROM ${NODE_IMAGE} AS console

# Build the Ant Design console.  The output lands in the Python package's
# static directory, so the runtime stage only has to copy the source tree.
WORKDIR /console
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build


FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/sub2api-mcp/venv \
    UV_LINK_MODE=copy \
    PYTHONPATH=/opt/sub2api-mcp/src:/opt/sub2api-core \
    SUB2API_MCP_LEGACY_CORE_ROOT=/opt/sub2api-core

COPY --from=uv /uv /uvx /usr/local/bin/

RUN groupadd --gid 10001 sub2api \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/sub2api sub2api \
    && mkdir -p /opt/sub2api-mcp /opt/sub2api-core /data \
    && chown -R sub2api:sub2api /opt/sub2api-mcp /opt/sub2api-core /data

WORKDIR /opt/sub2api-mcp

COPY --chown=sub2api:sub2api pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=sub2api:sub2api src ./src
# The console build output replaces whatever the source tree shipped, so the
# image always carries assets that match this revision.  In the console stage
# the Vite root is /console and it writes to ../src/..., giving /src.
COPY --from=console --chown=sub2api:sub2api \
    /src/sub2api_mcp/guardian/static \
    /opt/sub2api-mcp/src/sub2api_mcp/guardian/static
COPY --chown=sub2api:sub2api README.md ./README.md
COPY --chown=sub2api:sub2api core/*.py /opt/sub2api-core/
COPY --chown=sub2api:sub2api core/assets /opt/sub2api-core/assets

USER 10001:10001
EXPOSE 5310

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["/opt/sub2api-mcp/venv/bin/python", "-c", "import os,urllib.request; p=os.getenv('SUB2API_MCP_PORT','5310'); urllib.request.urlopen(f'http://127.0.0.1:{p}/healthz',timeout=3).read()"]

ENTRYPOINT ["/opt/sub2api-mcp/venv/bin/python", "-m", "sub2api_mcp"]
