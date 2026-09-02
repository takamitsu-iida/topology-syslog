"""
サーバー起動エントリーポイント。

  python -m topology_syslog          # .env + 環境変数から設定を読み取ってAPIサーバーを起動
  topology-syslog                     # uv sync 後はコマンドとして実行可能
  topology-syslog -i file.txt         # ファイルからSYSLOGを読み込んでインシデントへ変換
  tail -f syslog.txt | topology-syslog -i  # パイプ（ストリーミング）

設定は環境変数 (.env ファイル可) で行う。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
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


def _run_ingest(args: argparse.Namespace) -> None:
    """ファイル/標準入力モード: SYSLOGをインシデントへ変換して標準出力へ出力する。"""
    import asyncio

    from topology_syslog.correlation.root_cause_inferencer import RootCauseInferencer
    from topology_syslog.ingestion.file_ingest import run_batch, run_stream
    from topology_syslog.ingestion.syslog_filter import SyslogFilter
    from topology_syslog.topology.graph_engine import GraphEngine
    from topology_syslog.topology.yang_loader import TopologyLoader, device_severity_map

    correlation_mode = os.getenv("CORRELATION_MODE", "immediate").lower()
    if correlation_mode not in {"immediate", "time_window"}:
        raise ValueError("CORRELATION_MODE must be one of: immediate, time_window")

    legacy_keys = [
        key for key in ("WINDOW_SEC", "BURST_WINDOW_SEC", "BURST_THRESHOLD", "WINDOW_EXTEND_FACTOR", "WINDOW_SEC_MAX")
        if os.getenv(key) is not None
    ]
    if legacy_keys:
        logging.getLogger(__name__).warning(
            "Legacy window settings (%s) are deprecated in immediate mode and ignored. "
            "Use CORRELATION_MODE=immediate instead.",
            ", ".join(legacy_keys),
        )

    topology_path = args.topology or os.getenv("TOPOLOGY_PATH")
    if not topology_path:
        print(
            "エラー: トポロジーファイルが指定されていません。"
            " -t / --topology オプションか TOPOLOGY_PATH 環境変数で指定してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    topology_source = os.getenv("TOPOLOGY_SOURCE", "iida-yaml")
    loader = TopologyLoader()
    g = (
        loader.load_from_iida_json(topology_path)
        if topology_source == "ietf-json"
        else loader.load_from_iida_yaml(topology_path)
    )
    graph = GraphEngine(g)

    ignore_file = os.getenv("SYSLOG_IGNORE_FILE")
    syslog_filter: SyslogFilter | None = (
        SyslogFilter.from_file(ignore_file) if ignore_file else SyslogFilter()
    )
    syslog_filter.update_device_severity(device_severity_map(g))

    inferencer = RootCauseInferencer(
        severity_threshold=int(os.getenv("INFERENCE_SEVERITY_THRESHOLD", "5")),
        flapping_threshold=int(os.getenv("FLAPPING_THRESHOLD", "3")),
    )

    window_sec = int(os.getenv("WINDOW_SEC", "30"))

    store = None
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        from topology_syslog.persistence.incident_store import IncidentStore
        store = IncidentStore(database_url)

    maintenance_checker = None
    maintenance_dir = os.getenv("MAINTENANCE_DIR")
    if maintenance_dir:
        from topology_syslog.maintenance.checker import MaintenanceChecker
        maintenance_checker = MaintenanceChecker(maintenance_dir)

    output_json: bool = args.json

    notifier = None
    vigil_url = args.vigil_url or os.getenv("VIGIL_URL")
    if vigil_url:
        from topology_syslog.notification.vigil import VigilNotifier
        vigil_team = args.vigil_team or os.getenv("VIGIL_TEAM", "default")
        notifier = VigilNotifier(vigil_url, team_name=vigil_team)
        _logger.info("Vigil 転送を有効化: %s (team=%s)", vigil_url, vigil_team)

    file_path: str = args.ingest  # "-" or filename
    if file_path == "-":
        count = asyncio.run(
            run_stream(
                graph,
                inferencer,
                syslog_filter=syslog_filter,
                window_sec=window_sec,
                output_json=output_json,
                store=store,
                maintenance_checker=maintenance_checker,
                notifier=notifier,
            )
        )
    else:
        count = run_batch(
            file_path,
            graph,
            inferencer,
            syslog_filter=syslog_filter,
            window_sec=window_sec,
            output_json=output_json,
            store=store,
            maintenance_checker=maintenance_checker,
            notifier=notifier,
        )

    print(f"\n{count} incident(s) found.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="topology-syslog",
        description="Syslog → Incident 変換ツール / API サーバー",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  topology-syslog                            # API サーバー起動\n"
            "  topology-syslog -i syslog.txt              # ファイル一括処理\n"
            "  topology-syslog -i                         # 標準入力（EOF まで読む）\n"
            "  tail -f syslog.txt | topology-syslog -i    # パイプ（ストリーミング）\n"
        ),
    )
    parser.add_argument(
        "-i", "--ingest",
        nargs="?",
        const="-",
        metavar="FILE",
        help="SYSLOG ファイルを読み込んでインシデントへ変換する（省略時は標準入力）",
    )
    parser.add_argument(
        "-t", "--topology",
        metavar="FILE",
        help="トポロジー定義ファイル（TOPOLOGY_PATH 環境変数でも指定可）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="インシデントを JSON Lines 形式で出力する",
    )
    parser.add_argument(
        "--vigil-url",
        metavar="URL",
        help="vigil の ベース URL（例: http://vigil:8000）。VIGIL_URL 環境変数でも指定可",
    )
    parser.add_argument(
        "--vigil-team",
        metavar="TEAM",
        default=None,
        help="vigil へ転送する際のチーム名（デフォルト: default）。VIGIL_TEAM 環境変数でも指定可",
    )
    args = parser.parse_args()

    _load_env()

    log_level = os.getenv("LOG_LEVEL", "info").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )

    correlation_mode = os.getenv("CORRELATION_MODE", "immediate").lower()
    if correlation_mode not in {"immediate", "time_window"}:
        raise ValueError("CORRELATION_MODE must be one of: immediate, time_window")

    if args.ingest is not None:
        _run_ingest(args)
        return

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
        correlation_mode=correlation_mode,
        window_sec=int(os.getenv("WINDOW_SEC", "30")),
        burst_window_sec=float(os.getenv("BURST_WINDOW_SEC", "5.0")),
        burst_threshold=int(os.getenv("BURST_THRESHOLD", "3")),
        window_extend_factor=float(os.getenv("WINDOW_EXTEND_FACTOR", "2.0")),
        window_sec_max=int(os.getenv("WINDOW_SEC_MAX", "120")),
        inference_severity_threshold=int(os.getenv("INFERENCE_SEVERITY_THRESHOLD", "5")),
        flapping_threshold=int(os.getenv("FLAPPING_THRESHOLD", "3")),
        recovery_quiet_period_sec=float(os.getenv("RECOVERY_QUIET_PERIOD_SEC", "30.0")),
        recovery_flap_threshold=int(os.getenv("RECOVERY_FLAP_THRESHOLD", "2")),
        ai_enabled=os.getenv("AI_ENABLED", "false").lower() == "true",
        ai_rag_path=os.getenv("AI_RAG_PATH", ".chromadb"),
        ai_cache_ttl_days=int(os.getenv("AI_CACHE_TTL_DAYS", "7")),
        vigil_url=os.getenv("VIGIL_URL") or None,
        vigil_team_name=os.getenv("VIGIL_TEAM", "default"),
        investigation_enabled=os.getenv("INVESTIGATION_ENABLED", "false").lower() == "true",
        investigation_testbed_file=os.getenv("PYATS_TESTBED_FILE") or None,
        investigation_max_turns=int(os.getenv("INVESTIGATION_MAX_TURNS", "8")),
        investigation_command_timeout=int(os.getenv("INVESTIGATION_COMMAND_TIMEOUT", "30")),
        maintenance_dir=os.getenv("MAINTENANCE_DIR") or None,
        knowledge_path=os.getenv("SKB_PATH") or None,
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
