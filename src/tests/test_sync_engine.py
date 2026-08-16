import threading
import time
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

from topology_syslog.topology.graph_engine import GraphEngine
from topology_syslog.topology.sync_engine import (
    TopologySyncEngine,
    _graph_changed,
    _xml_to_iida_dict,
)


# ---- _graph_changed ------------------------------------------------

def test_graph_changed_detects_different_edges():
    g1 = nx.DiGraph(); g1.add_edge("A", "B")
    g2 = nx.DiGraph(); g2.add_edge("A", "C")
    assert _graph_changed(GraphEngine(g1), g2) is True


def test_graph_changed_same_edges_returns_false():
    g1 = nx.DiGraph(); g1.add_edge("A", "B")
    g2 = nx.DiGraph(); g2.add_edge("A", "B")
    assert _graph_changed(GraphEngine(g1), g2) is False


def test_graph_changed_empty_to_nonempty():
    empty = nx.DiGraph()
    g = nx.DiGraph(); g.add_edge("A", "B")
    assert _graph_changed(GraphEngine(empty), g) is True


# ---- ポーリング ---------------------------------------------------

def test_polling_invokes_fetch_immediately():
    fetched = threading.Event()

    def fetch():
        fetched.set()
        return nx.DiGraph()

    engine = GraphEngine(nx.DiGraph())
    sync = TopologySyncEngine(engine)
    sync.start_polling(fetch, interval_sec=300)
    assert fetched.wait(timeout=2.0), "最初のポーリングが即座に実行されるべき"
    sync.stop()


def test_polling_updates_graph_on_change():
    old = nx.DiGraph(); old.add_edge("A", "B")
    new = nx.DiGraph(); new.add_edge("A", "C")
    done = threading.Event()

    def fetch():
        done.set()
        return new

    engine = GraphEngine(old)
    sync = TopologySyncEngine(engine)
    sync.start_polling(fetch, interval_sec=300)
    done.wait(timeout=2.0)
    sync.stop()

    assert ("A", "C") in engine.edges
    assert ("A", "B") not in engine.edges


def test_polling_skips_update_when_unchanged():
    g = nx.DiGraph(); g.add_edge("A", "B")
    done = threading.Event()

    def fetch():
        done.set()
        same = nx.DiGraph(); same.add_edge("A", "B")
        return same

    engine = GraphEngine(g)
    sync = TopologySyncEngine(engine)
    sync.start_polling(fetch, interval_sec=300)
    done.wait(timeout=2.0)
    sync.stop()

    # 変化なし → エッジはそのまま
    assert ("A", "B") in engine.edges


def test_stop_halts_polling():
    call_count = []

    def fetch():
        call_count.append(1)
        return nx.DiGraph()

    engine = GraphEngine(nx.DiGraph())
    sync = TopologySyncEngine(engine)
    sync.start_polling(fetch, interval_sec=300)
    time.sleep(0.1)
    sync.stop(timeout=2.0)
    count_after_stop = len(call_count)

    # 停止後は呼ばれない
    time.sleep(0.1)
    assert len(call_count) == count_after_stop


def test_start_polling_raises_if_already_running():
    engine = GraphEngine(nx.DiGraph())
    sync = TopologySyncEngine(engine)
    sync.start_polling(lambda: nx.DiGraph(), interval_sec=300)
    with pytest.raises(RuntimeError, match="already running"):
        sync.start_polling(lambda: nx.DiGraph(), interval_sec=300)
    sync.stop()


# ---- fetch_from_restconf ------------------------------------------

def test_fetch_from_restconf_builds_graph():
    _data = {
        "network-model": {
            "physical-layer": {
                "device": [
                    {"device-id": "R1", "role": "core"},
                    {"device-id": "SW1", "role": "access"},
                ],
                "physical-connection": [
                    {"endpoint": [
                        {"device-id": "R1",  "interface-id": "GE0/0"},
                        {"device-id": "SW1", "interface-id": "GE0/0"},
                    ]}
                ],
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = _data
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        sync = TopologySyncEngine(GraphEngine(nx.DiGraph()))
        g = sync.fetch_from_restconf("http://controller:8080", "token123")

    assert "R1" in g.nodes
    assert "SW1" in g.nodes
    call_url = mock_get.call_args.args[0]
    assert "restconf/data" in call_url
    assert "Bearer token123" in mock_get.call_args.kwargs["headers"]["Authorization"]


# ---- _xml_to_iida_dict --------------------------------------------

def test_xml_to_iida_dict_parses_devices_and_connections():
    NS = "urn:ietf:params:xml:ns:yang:iida-network-model"
    xml_str = f"""<data>
  <physical-layer xmlns="{NS}">
    <device>
      <device-id>R1</device-id>
      <role>core</role>
    </device>
    <device>
      <device-id>SW1</device-id>
      <role>access</role>
    </device>
    <physical-connection>
      <endpoint><device-id>R1</device-id></endpoint>
      <endpoint><device-id>SW1</device-id></endpoint>
    </physical-connection>
  </physical-layer>
</data>"""
    data = _xml_to_iida_dict(xml_str)
    physical = data["network-model"]["physical-layer"]
    assert len(physical["device"]) == 2
    assert physical["device"][0]["device-id"] == "R1"
    assert physical["device"][0]["role"] == "core"
    assert len(physical["physical-connection"]) == 1
    assert physical["physical-connection"][0]["endpoint"][0]["device-id"] == "R1"


def test_xml_to_iida_dict_missing_physical_layer_returns_empty():
    data = _xml_to_iida_dict("<data/>")
    physical = data["network-model"]["physical-layer"]
    assert physical["device"] == []
    assert physical["physical-connection"] == []
