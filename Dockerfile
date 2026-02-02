# Agent Infrastructure Platform - Docker Image

FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir build

# Build wheel
COPY src ./src
RUN python -m build --wheel

# Production image
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libffi8 \
    && rm -rf /var/lib/apt/lists/*

# Copy and install wheel
COPY --from=builder /app/dist/*.whl .
RUN pip install --no-cache-dir *.whl && rm *.whl

# Create non-root user
RUN useradd -m -u 1000 aip && \
    chown -R aip:aip /app
USER aip

# Expose ports
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import agent_infrastructure_platform; print('OK')" || exit 1

# Default command
CMD ["python", "-m", "agent_infrastructure_platform.cli", "serve"]
