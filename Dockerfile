# Python 3.11 base image
FROM python:3.11-slim

# Metadata
LABEL maintainer="APK Sender Service"
LABEL description="Telegram APK file uploader service"

# Working directory
WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better Docker layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p sessions uploads && \
    chmod -R 755 sessions uploads

# Environment variables (default values)
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8000

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs', timeout=5)" || exit 1

# Run the application
CMD ["sh", "-c", "uvicorn api:app --host ${HOST} --port ${PORT} --timeout-keep-alive 600 --timeout-graceful-shutdown 600 --limit-concurrency 10 --limit-max-requests 1000"]

