FROM python:3.13-slim

# System deps for grpcio + Tailscale
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ curl iptables && \
    curl -fsSL https://tailscale.com/install.sh | sh && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (client-only subset)
COPY client_web_ui/requirements-cloud.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY client_web_ui/ ./client_web_ui/

# Entrypoint: start Tailscale, then gunicorn
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Cloud Run sets PORT env var (default 8080)
ENV PORT=8080

EXPOSE ${PORT}

CMD ["./entrypoint.sh"]
