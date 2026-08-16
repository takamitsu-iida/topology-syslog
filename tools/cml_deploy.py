#!/usr/bin/env python3
"""CML ラボ管理 CLI

環境変数 (.env ファイルまたはシェル) から接続情報を読み取る:
  CML_URL         例: https://192.168.0.10
  CML_USERNAME    例: admin
  CML_PASSWORD    例: cisco123
  CML_VERIFY_SSL  "false" にすると SSL 検証をスキップ (自己署名証明書向け)

使い方:
  python tools/cml_deploy.py deploy [cml_lab.yaml]   # インポート & 起動
  python tools/cml_deploy.py deploy --no-start ...    # インポートのみ
  python tools/cml_deploy.py ls                       # ラボ一覧
  python tools/cml_deploy.py status <lab-id>          # ステータス確認
  python tools/cml_deploy.py stop <lab-id>            # 停止 & 削除
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
import yaml


# ---------------------------------------------------------------------------
# .env ローダー (python-dotenv が不要なシンプル実装)
# ---------------------------------------------------------------------------

def _load_env_file(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


# ---------------------------------------------------------------------------
# CML REST API クライアント
# ---------------------------------------------------------------------------

def _client(url: str, verify: bool) -> httpx.Client:
    return httpx.Client(base_url=url, verify=verify, timeout=60.0)


def _auth(client: httpx.Client, username: str, password: str) -> str:
    """認証して JWT トークンを返す。"""
    resp = client.post(
        "/api/v0/authenticate",
        json={"username": username, "password": password},
    )
    resp.raise_for_status()
    token = resp.json()
    # CML は token 文字列を直接返すこともある
    return token if isinstance(token, str) else token.get("token", token)


def _import_lab(client: httpx.Client, token: str, topology_yaml: str) -> str:
    """topology YAML をインポートしてラボ ID を返す。"""
    resp = client.post(
        "/api/v0/import",
        content=topology_yaml.encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/plain; charset=utf-8",
        },
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _start_lab(client: httpx.Client, token: str, lab_id: str) -> None:
    client.put(
        f"/api/v0/labs/{lab_id}/start",
        headers={"Authorization": f"Bearer {token}"},
    ).raise_for_status()


def _stop_lab(client: httpx.Client, token: str, lab_id: str) -> None:
    client.put(
        f"/api/v0/labs/{lab_id}/stop",
        headers={"Authorization": f"Bearer {token}"},
    ).raise_for_status()


def _delete_lab(client: httpx.Client, token: str, lab_id: str) -> None:
    client.delete(
        f"/api/v0/labs/{lab_id}",
        headers={"Authorization": f"Bearer {token}"},
    ).raise_for_status()


def _get_lab(client: httpx.Client, token: str, lab_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get(f"/api/v0/labs/{lab_id}", headers=headers)
    resp.raise_for_status()
    lab = resp.json()
    # CML 2.10+: title は /topology エンドポイントから取得する
    if not lab.get("title"):
        try:
            tr = client.get(
                f"/api/v0/labs/{lab_id}/topology",
                params={"exclude_configurations": "true"},
                headers=headers,
            )
            if tr.is_success:
                topo = tr.json()
                lab_info = topo.get("lab")
                if isinstance(lab_info, dict):
                    # 新スキーマ: {"lab": {"title": ...}, ...}
                    lab["title"] = lab_info.get("title", "")
                else:
                    # 旧スキーマ: {"lab_title": ...}
                    lab["title"] = topo.get("lab_title", "")
        except Exception:
            pass
    return lab


def _list_labs(client: httpx.Client, token: str) -> list[str]:
    """ラボ ID の一覧を返す。"""
    resp = client.get(
        "/api/v0/labs",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return resp.json()


def _find_lab_by_title(client: httpx.Client, token: str, title: str) -> dict | None:
    """同じタイトルのラボを返す。見つからない場合は None。"""
    for lid in _list_labs(client, token):
        try:
            lab = _get_lab(client, token, lid)
            if lab.get("title") == title:
                return lab
        except httpx.HTTPStatusError:
            pass
    return None


# ---------------------------------------------------------------------------
# 表示ヘルパー
# ---------------------------------------------------------------------------

def _print_lab(lab: dict) -> None:
    print(f"  ID    : {lab.get('id', '?')}")
    print(f"  Title : {lab.get('title', '?')}")
    print(f"  State : {lab.get('state', '?')}")
    nodes = lab.get("nodes", [])
    if nodes:
        print(f"  Nodes ({len(nodes)}):")
        for nd in nodes:
            label = nd.get("label") or nd.get("id", "?")
            state = nd.get("state", "?")
            print(f"    {label:25}  {state}")


# ---------------------------------------------------------------------------
# サブコマンド実装
# ---------------------------------------------------------------------------

def cmd_deploy(client: httpx.Client, token: str, args: argparse.Namespace) -> int:
    topo_path = Path(args.topology)
    if not topo_path.exists():
        print(f"[ERROR] topology ファイルが見つかりません: {topo_path}", file=sys.stderr)
        return 1

    topology_yaml = topo_path.read_text(encoding="utf-8")

    # cml_lab.yaml からラボタイトルを取得して重複チェック
    lab_title: str = yaml.safe_load(topology_yaml).get("lab", {}).get("title", "")
    if lab_title:
        print(f"[*] 既存ラボを確認中 (title={lab_title!r}) ...")
        existing = _find_lab_by_title(client, token, lab_title)
        if existing:
            print(f"[WARN] 同名のラボが既に存在します:")
            _print_lab(existing)
            if not args.force:
                print(
                    "\n同名ラボが存在するため停止しました。"
                    "\n  上書きデプロイ: --force"
                    "\n  既存ラボ削除  : python tools/cml_deploy.py stop "
                    + existing['id']
                )
                return 1
            # --force: 既存ラボを停止・削除してから再デプロイ
            print(f"[*] --force: 既存ラボを停止・削除します ({existing['id']}) ...")
            try:
                _stop_lab(client, token, existing["id"])
            except httpx.HTTPStatusError:
                pass  # 既に停止済みの場合は無視
            try:
                _delete_lab(client, token, existing["id"])
                print(f"[+] 削除完了")
            except httpx.HTTPStatusError as e:
                print(f"[ERROR] 既存ラボの削除に失敗しました ({e.response.status_code})",
                      file=sys.stderr)
                return 1

    print(f"[*] topology をインポート中: {topo_path} ...")
    try:
        lab_id = _import_lab(client, token, topology_yaml)
    except httpx.HTTPStatusError as e:
        print(f"[ERROR] インポート失敗 ({e.response.status_code}): {e.response.text}",
              file=sys.stderr)
        return 1

    print(f"[+] インポート成功  lab_id = {lab_id}")

    if args.no_start:
        print("[*] --no-start 指定のため起動をスキップします")
        return 0

    print(f"[*] ラボを起動中: {lab_id} ...")
    try:
        _start_lab(client, token, lab_id)
    except httpx.HTTPStatusError as e:
        print(f"[ERROR] 起動失敗 ({e.response.status_code})", file=sys.stderr)
        return 1

    print("[+] 起動コマンド送信完了 (ノードの起動には数分かかる場合があります)")
    try:
        lab = _get_lab(client, token, lab_id)
        # API がタイトルを返さない場合は YAML から取得済みの値を補完
        if not lab.get("title") and lab_title:
            lab["title"] = lab_title
        print("\n[ラボ情報]")
        _print_lab(lab)
    except httpx.HTTPStatusError:
        pass  # ステータス取得失敗は無視
    return 0


def cmd_stop(client: httpx.Client, token: str, args: argparse.Namespace) -> int:
    lab_id = args.lab_id
    print(f"[*] ラボを停止中: {lab_id} ...")
    try:
        _stop_lab(client, token, lab_id)
        print("[+] 停止完了")
    except httpx.HTTPStatusError as e:
        print(f"[WARN] 停止エラー ({e.response.status_code}) — 削除を続行します",
              file=sys.stderr)

    print(f"[*] ラボを削除中: {lab_id} ...")
    try:
        _delete_lab(client, token, lab_id)
        print("[+] 削除完了")
    except httpx.HTTPStatusError as e:
        print(f"[ERROR] 削除失敗 ({e.response.status_code})", file=sys.stderr)
        return 1
    return 0


def cmd_status(client: httpx.Client, token: str, args: argparse.Namespace) -> int:
    try:
        lab = _get_lab(client, token, args.lab_id)
        print("[ラボ情報]")
        _print_lab(lab)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            print(f"[ERROR] ラボが見つかりません: {args.lab_id}", file=sys.stderr)
        else:
            print(f"[ERROR] {e.response.status_code}", file=sys.stderr)
        return 1
    return 0


def cmd_ls(client: httpx.Client, token: str, _args: argparse.Namespace) -> int:
    try:
        lab_ids = _list_labs(client, token)
    except httpx.HTTPStatusError as e:
        print(f"[ERROR] {e.response.status_code}", file=sys.stderr)
        return 1

    if not lab_ids:
        print("ラボなし")
        return 0

    print(f"{'ラボ ID':38}  {'Title':30}  {'State'}")
    print("-" * 80)
    for lid in lab_ids:
        try:
            lab = _get_lab(client, token, lid)
            print(f"{lid:38}  {lab.get('title','?'):30}  {lab.get('state','?')}")
        except httpx.HTTPStatusError:
            print(f"{lid:38}  (取得失敗)")
    return 0


# ---------------------------------------------------------------------------
# メインエントリー
# ---------------------------------------------------------------------------

_DEFAULT_TOPOLOGY = str(
    Path(__file__).parent.parent / "configs" / "clos" / "cml_lab.yaml"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cml_deploy",
        description="CML ラボ管理 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # 接続オプション (環境変数がデフォルト)
    conn = parser.add_argument_group("接続オプション")
    conn.add_argument("--url",      default=None, metavar="URL",
                      help="CML URL (env: CML_URL)")
    conn.add_argument("--username", default=None, metavar="USER",
                      help="CML ユーザー名 (env: CML_USERNAME)")
    conn.add_argument("--password", default=None, metavar="PASS",
                      help="CML パスワード (env: CML_PASSWORD)")
    conn.add_argument("--no-verify-ssl", action="store_true", default=None,
                      help="SSL 証明書を検証しない (env: CML_VERIFY_SSL=false)")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # deploy
    dp = sub.add_parser("deploy", help="topology をインポートして起動する")
    dp.add_argument(
        "topology", nargs="?", default=_DEFAULT_TOPOLOGY,
        help=f"cml_lab.yaml のパス (デフォルト: {_DEFAULT_TOPOLOGY})",
    )
    dp.add_argument("--no-start", action="store_true",
                    help="インポートのみ (起動しない)")
    dp.add_argument("--force", action="store_true",
                    help="同名ラボが存在する場合に削除して再デプロイする")

    # stop
    sp = sub.add_parser("stop", help="ラボを停止して削除する")
    sp.add_argument("lab_id", help="ラボ ID")

    # status
    stp = sub.add_parser("status", help="ラボのステータスを表示する")
    stp.add_argument("lab_id", help="ラボ ID")

    # ls
    sub.add_parser("ls", help="全ラボを一覧表示する")

    return parser


def main() -> int:
    _load_env_file()  # プロジェクトルートの .env を読む

    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    # 接続情報の解決 (CLI引数 > 環境変数)
    url      = args.url      or os.environ.get("CML_URL")
    username = args.username or os.environ.get("CML_USERNAME")
    password = args.password or os.environ.get("CML_PASSWORD")

    if args.no_verify_ssl is None:
        verify_ssl = os.environ.get("CML_VERIFY_SSL", "true").lower() not in ("false", "0", "no")
    else:
        verify_ssl = not args.no_verify_ssl

    missing = [n for n, v in [("CML_URL", url), ("CML_USERNAME", username),
                               ("CML_PASSWORD", password)] if not v]
    if missing:
        print(f"[ERROR] 必須の接続情報が不足しています: {', '.join(missing)}\n"
              f"       .env ファイルまたは環境変数を設定してください", file=sys.stderr)
        return 1

    print(f"[*] CML {url} に接続中 (SSL検証: {verify_ssl}) ...")
    try:
        with _client(url, verify=verify_ssl) as client:
            token = _auth(client, username, password)
            print("[+] 認証成功\n")

            dispatch = {
                "deploy": cmd_deploy,
                "stop":   cmd_stop,
                "status": cmd_status,
                "ls":     cmd_ls,
            }
            return dispatch[args.command](client, token, args)

    except httpx.RequestError as e:
        print(f"[ERROR] 接続エラー: {e}", file=sys.stderr)
        return 1
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            print(f"[ERROR] 認証失敗 ({e.response.status_code}): "
                  f"ユーザー名/パスワードを確認してください", file=sys.stderr)
        else:
            print(f"[ERROR] HTTP {e.response.status_code}: {e.response.text}",
                  file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
