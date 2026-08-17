FROM python:3.12-slim

WORKDIR /app

# 依存パッケージを先にインストールしてレイヤーキャッシュを活用
COPY pyproject.toml .
COPY src/ ./src/

RUN pip install --no-cache-dir .

EXPOSE 8080
EXPOSE 1514/udp

CMD ["topology-syslog"]
