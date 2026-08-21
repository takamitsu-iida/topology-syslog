"""pyATS testbed YAML ファイルから Testbed オブジェクトを生成。

testbed YAML（configs/clos/testbed.yaml 等）を startup 時に一度パースして保持する。
build_for() を呼ぶたびに新規 Testbed インスタンスを生成することでスレッドセーフを確保する。
"""
from __future__ import annotations

import logging

import yaml

_logger = logging.getLogger(__name__)


class TestbedBuilder:
    def __init__(self, testbed_path: str) -> None:
        with open(testbed_path) as f:
            self._testbed_dict: dict = yaml.safe_load(f)
        known = list((self._testbed_dict.get("devices") or {}).keys())
        _logger.info("Testbed loaded: %d devices %s (%s)", len(known), known, testbed_path)

    def build_for(self, device_id: str):
        """指定デバイスを含む pyATS Testbed を返す。"""
        from pyats.topology import loader  # lazy import — optional dep

        devices = self._testbed_dict.get("devices") or {}
        if device_id not in devices:
            raise ValueError(
                f"デバイス {device_id!r} は testbed に存在しません "
                f"(登録済み: {list(devices.keys())})"
            )
        return loader.load(self._testbed_dict)

    @property
    def known_devices(self) -> list[str]:
        return list((self._testbed_dict.get("devices") or {}).keys())
