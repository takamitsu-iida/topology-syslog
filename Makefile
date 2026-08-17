.DEFAULT_GOAL := help

# uv がインストール直後で PATH 未反映のケースに備える
export PATH := $(HOME)/.local/bin:$(PATH)

# ── 設定（環境変数で上書き可） ─────────────────────────────────────────────
TOPOLOGY_PATH   ?= configs/clos/yang_topology.yaml
TOPOLOGY_SOURCE ?= iida-yaml
IGNORE_FILE     ?= configs/clos/syslog_ignore.txt
API_HOST        ?= 0.0.0.0
API_PORT        ?= 8080
SYSLOG_HOST     ?= 0.0.0.0
SYSLOG_PORT     ?= 1514

PID_DIR := .pids
LOG_DIR := logs
API_PID := $(PID_DIR)/api.pid
UI_PID  := $(PID_DIR)/ui.pid
API_LOG := $(LOG_DIR)/api.log
UI_LOG  := $(LOG_DIR)/ui.log

# ── ヘルプ ────────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo "使用可能なターゲット:"
	@echo "  make start      バックエンド + フロントエンドを起動"
	@echo "  make stop       両プロセスを停止"
	@echo "  make restart    停止してから再起動"
	@echo "  make status     プロセス状態を確認"
	@echo "  make logs-api   バックエンドのログを tail -f"
	@echo "  make logs-ui    フロントエンドのログを tail -f"
	@echo "  make test       pytest を実行"
	@echo "  make install    依存パッケージをインストール（uv sync + npm install）"
	@echo "  make setup      初回セットアップ（uv インストール / サブモジュール / uv sync）"
	@echo ""
	@echo "個別操作: start-api / stop-api / start-ui / stop-ui"

# ── 起動 ─────────────────────────────────────────────────────────────────
.PHONY: start start-api start-ui
start: start-api start-ui
	@echo ""
	@echo "  API : http://localhost:$(API_PORT)"
	@echo "  UI  : http://localhost:3000"

start-api: | $(PID_DIR) $(LOG_DIR)
	@if [ -f $(API_PID) ] && kill -0 "$$(cat $(API_PID))" 2>/dev/null; then \
		echo "API already running (PID $$(cat $(API_PID)))"; \
	else \
		TOPOLOGY_PATH=$(TOPOLOGY_PATH) \
		TOPOLOGY_SOURCE=$(TOPOLOGY_SOURCE) \
		SYSLOG_IGNORE_FILE=$(IGNORE_FILE) \
		API_HOST=$(API_HOST) \
		API_PORT=$(API_PORT) \
		SYSLOG_HOST=$(SYSLOG_HOST) \
		SYSLOG_PORT=$(SYSLOG_PORT) \
		uv run python -m topology_syslog >"$(CURDIR)/$(API_LOG)" 2>&1 & echo $$! >"$(CURDIR)/$(API_PID)"; \
		echo "API started (PID $$(cat $(API_PID))) — log: $(API_LOG)"; \
	fi

start-ui: | $(PID_DIR) $(LOG_DIR)
	@if [ -f $(UI_PID) ] && kill -0 "$$(cat $(UI_PID))" 2>/dev/null; then \
		echo "UI  already running (PID $$(cat $(UI_PID)))"; \
	else \
		cd frontend && npm run dev >"$(CURDIR)/$(UI_LOG)" 2>&1 & echo $$! >"$(CURDIR)/$(UI_PID)"; \
		echo "UI  started (PID $$(cat $(UI_PID))) — log: $(UI_LOG)"; \
	fi

# ── 停止 ─────────────────────────────────────────────────────────────────
.PHONY: stop stop-api stop-ui
stop: stop-api stop-ui

stop-api:
	@if [ -f $(API_PID) ] && kill -0 "$$(cat $(API_PID))" 2>/dev/null; then \
		kill "$$(cat $(API_PID))" && rm -f $(API_PID) && echo "API stopped"; \
	else \
		echo "API not running"; rm -f $(API_PID); \
	fi

stop-ui:
	@if [ -f $(UI_PID) ] && kill -0 "$$(cat $(UI_PID))" 2>/dev/null; then \
		kill "$$(cat $(UI_PID))" && rm -f $(UI_PID) && echo "UI  stopped"; \
	else \
		echo "UI  not running"; rm -f $(UI_PID); \
	fi

# ── 再起動 ───────────────────────────────────────────────────────────────
.PHONY: restart
restart: stop start

# ── 状態確認 ─────────────────────────────────────────────────────────────
.PHONY: status
status:
	@if [ -f $(API_PID) ] && kill -0 "$$(cat $(API_PID))" 2>/dev/null; then \
		echo "API: running (PID $$(cat $(API_PID)))"; \
	else \
		echo "API: stopped"; \
	fi
	@if [ -f $(UI_PID) ] && kill -0 "$$(cat $(UI_PID))" 2>/dev/null; then \
		echo "UI:  running (PID $$(cat $(UI_PID)))"; \
	else \
		echo "UI:  stopped"; \
	fi

# ── ログ ─────────────────────────────────────────────────────────────────
.PHONY: logs-api logs-ui
logs-api:
	tail -f $(API_LOG)

logs-ui:
	tail -f $(UI_LOG)

# ── テスト / インストール / セットアップ ─────────────────────────────────
.PHONY: test install setup
test:
	uv run python -m pytest src/tests/ -v

install:
	uv sync
	cd frontend && npm install

# 初回セットアップ: npm 確認 → uv → サブモジュール → uv sync → npm install
setup:
	@if ! command -v npm >/dev/null 2>&1; then \
		echo "ERROR: npm が見つかりません。Node.js をインストールしてから再実行してください。"; \
		echo "  https://nodejs.org/"; \
		exit 1; \
	fi
	@if ! command -v uv >/dev/null 2>&1; then \
		echo "Installing uv..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	else \
		echo "uv: $$(uv --version)"; \
	fi
	@if [ -z "$$(ls yang/*.yang 2>/dev/null)" ]; then \
		echo "Fetching yang submodule..."; \
		git submodule update --init --recursive; \
	else \
		echo "yang submodule: ok"; \
	fi
	uv sync
	cd frontend && npm install
	@echo ""
	@echo "セットアップ完了 — make start でサーバーを起動できます"

# ── ディレクトリ自動作成 ──────────────────────────────────────────────────
$(PID_DIR) $(LOG_DIR):
	mkdir -p $@
