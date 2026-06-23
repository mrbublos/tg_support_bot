FROM python:3.14-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV IS_DOCKER=True

# Set working directory
WORKDIR /app

# Create a non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Install system dependencies (if any)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY code/ ./code/
COPY shared/ ./shared/

# Create necessary directories with proper permissions
RUN mkdir -p /app/shared && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Run migrations and start the application
CMD ["sh", "-c", "cd /app/code && ./run.py migrate; ./run.py"]