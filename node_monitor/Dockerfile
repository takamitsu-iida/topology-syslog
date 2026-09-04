FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ ./src/

RUN apt-get update \
    && apt-get install --no-install-recommends -y iputils-ping \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir .

EXPOSE 8090

CMD ["python", "-m", "topology_syslog.node_monitor"]