# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock* ./

# Install production dependencies only
RUN uv sync --frozen --no-dev

# Copy application source
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY scripts/ scripts/

# Stage 2: Production image
FROM python:3.12-slim

WORKDIR /app

# Create non-root user for security, install pg tools for backup/migrations
RUN useradd -m -r appuser \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy built application from builder
COPY --from=builder /app /app

# Use non-root user
USER appuser

# Cloud Run sets PORT; default to 8080
ENV PORT=8080
EXPOSE 8080

# Run uvicorn via the venv created by uv
CMD ["/app/.venv/bin/uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
