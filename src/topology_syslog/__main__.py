"""
サーバー起動エントリーポイント。

  python -m topology_syslog        # .env + 環境変数から設定を読み取って起動
  topology-syslog                   # uv sync 後はコマンドとして実行可能

設定は環境変数 (.env ファイル可) で行う。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path


def _load_env(path: str = ".env") -> None:
    """シンプルな .env ローダー。既にセット済みの変数は上書きしない。"""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    _load_env()

    log_level = os.getenv("LOG_LEVEL", "info").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )

    import uvicorn
    from topology_syslog.api.main import create_app

    cors_raw = os.getenv("CORS_ORIGINS", "*")
    cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()] or None

    app = create_app(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./incidents.db"),
        topology_path=os.getenv("TOPOLOGY_PATH") or None,
        topology_source=os.getenv("TOPOLOGY_SOURCE", "iida-yaml"),
        ignore_file=os.getenv("SYSLOG_IGNORE_FILE") or None,
        cors_origins=cors_origins,
        syslog_host=os.getenv("SYSLOG_HOST", "0.0.0.0"),
        syslog_port=int(os.getenv("SYSLOG_PORT", "1514")),
        window_sec=int(os.getenv("WINDOW_SEC", "30")),
    )

    uvicorn.run(
        app,
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8080")),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


# create_app に syslog_host/syslog_port を渡す必要があるため main() を更新


if __name__ == "__main__":
    main()
