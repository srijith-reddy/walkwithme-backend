FROM python:3.11-slim

# -----------------------------------------------------
# System dependencies for Shapely + Rtree
# -----------------------------------------------------
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    libgeos-dev \
    libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------
# Create app directory
# -----------------------------------------------------
WORKDIR /app

# -----------------------------------------------------
# Copy backend (including WKB + R-tree files)
# -----------------------------------------------------
COPY backend/ /app/backend/

# -----------------------------------------------------
# Copy requirements
# -----------------------------------------------------
COPY requirements.txt /app/

# -----------------------------------------------------
# Install Python dependencies
# -----------------------------------------------------
RUN pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------
# Expose port
# -----------------------------------------------------
EXPOSE 8080

# -----------------------------------------------------
# Start FastAPI
# -----------------------------------------------------
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
