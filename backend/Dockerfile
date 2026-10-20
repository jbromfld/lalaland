FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv
FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641

COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./

# Install production dependencies before copying source so code changes can reuse
# this layer. Require the lockfile to be current, skip the application itself,
# and require dependency wheels instead of building packages from source.
# The BuildKit cache mount reuses uv downloads without adding them to the image.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project --no-build

COPY backend ./backend
COPY frontend ./frontend

# Install the copied application as a regular package rather than an editable
# source checkout, keeping production dependencies synchronized with the lockfile.
# Reuse the same download cache while building and installing the application.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
