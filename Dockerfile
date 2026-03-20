FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

ENV AWRASS_PORT=7777
ENV AWRASS_HOST=0.0.0.0
ENV AWRASS_HEADLESS=true
ENV AWRASS_POOL_SIZE=2

EXPOSE 7777
CMD ["python", "main.py"]
