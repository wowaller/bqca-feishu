# Use a lightweight Python base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Set working directory
WORKDIR /app

# Install system dependencies needed for building packages or fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file first for optimal Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source code
COPY . .

# Create the directory for temporary charts
RUN mkdir -p tmp_charts

# Expose the port (Cloud Run requires this, though we run a dummy listener in python)
EXPOSE 8080

# Run the bot server
CMD ["python", "-u", "bot.py"]
