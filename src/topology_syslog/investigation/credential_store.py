"""デバイス認証情報の管理。

優先順位:
  1. 環境変数 DEVICE_CREDENTIALS (JSON 文字列)
  2. 引数で指定した YAML ファイル

YAML / JSON 形式:
  Spine1:
    ip: "192.168.1.1"   # 管理 IP アドレス
    username: admin
    password: "secret"  # または ssh_keyfile で鍵認証
    os: ios             # pyATS OS 種別: ios / iosxe / iosxr / nxos
    port: 22
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

import yaml

_logger = logging.getLogger(__name__)


@dataclass
class DeviceCredential:
    ip: str
    username: str
    os: str = "ios"
    password: str | None = None
    ssh_keyfile: str | None = None
    port: int = 22


class CredentialStore:
    def __init__(self, credential_file: str | None = None) -> None:
        self._creds: dict[str, DeviceCredential] = {}
        self._load_from_env()
        if credential_file:
            self._load_from_file(credential_file)

    def _load_from_env(self) -> None:
        raw = os.getenv("DEVICE_CREDENTIALS")
        if not raw:
            return
        try:
            data: dict = json.loads(raw)
            for dev_id, attrs in data.items():
                self._creds[dev_id] = DeviceCredential(**attrs)
        except (json.JSONDecodeError, TypeError) as exc:
            _logger.warning("DEVICE_CREDENTIALS の解析に失敗しました: %s", exc)

    def _load_from_file(self, path: str) -> None:
        if not os.path.exists(path):
            _logger.warning("認証情報ファイルが見つかりません: %s", path)
            return
        with open(path) as f:
            data: dict = yaml.safe_load(f) or {}
        for dev_id, attrs in data.items():
            self._creds[dev_id] = DeviceCredential(**attrs)
        _logger.info("認証情報を読み込みました: %d 台 (%s)", len(data), path)

    def get(self, device_id: str) -> DeviceCredential | None:
        return self._creds.get(device_id)

    @property
    def known_devices(self) -> list[str]:
        return list(self._creds.keys())
