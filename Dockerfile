FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Install build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev libssl-dev libc-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy application code to the container
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Define an entrypoint script for flexible command usage
ENTRYPOINT ["python"]

# Default command (can be overridden by docker-compose or runtime args)
CMD ["pulse.py"]
