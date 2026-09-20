# Multi-stage/Slim Python build for HawaGuide Backend
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Set working directory to /app
WORKDIR /app

# Install system dependencies required for psycopg2, PyKrige, Prophet, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch to avoid massive multi-GB CUDA dependencies
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Copy requirements and install remaining backend dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend application source code into /app/backend
COPY backend/ /app/backend/

# Expose backend port
EXPOSE 8000

# Run FastAPI backend via Uvicorn preserving the 'backend' namespace
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
