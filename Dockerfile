FROM python:3.12-slim

WORKDIR /app

# Install build dependencies for llama-cpp-python
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    cmake \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# copy requirements first for better caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.main"]
