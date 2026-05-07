FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package installation
RUN pip install uv

# Copy dependency files
COPY pyproject.toml ./
COPY backend/sentinelai ./sentinelai

# Install Python dependencies
RUN uv pip install --system -e .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

# Run the application
CMD ["uvicorn", "sentinelai.api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
