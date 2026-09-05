"""Causal topology model for hypothesis-based RCA.

This graph is separate from the legacy device-level GraphEngine.  It models
objects that can independently become root-cause candidates: devices,
interfaces, physical links, and BGP sessions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import yaml

_ROLE_PRIORITY: dict[str, int] = {
    "border": 0,
    "spine": 0,
    "core": 1,
    "distribution": 2,
    "access": 3,
    "leaf": 3,
    "oob": 4,
    "other": 5,
}


@dataclass(frozen=True)
class InterfaceEndpoint:
    device_id: str
    interface_id: str


@dataclass
class CausalTopology:
    graph: nx.DiGraph
    devices: set[str] = field(default_factory=set)
    interfaces: dict[tuple[str, str], str] = field(default_factory=dict)
    interface_links: dict[tuple[str, str], str] = field(default_factory=dict)
    bgp_sessions: dict[frozenset[str], str] = field(default_factory=dict)
    device_addresses: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load_from_iida_yaml(cls, path: str | Path) -> "CausalTopology":
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_iida_topology(data)

    @classmethod
    def load_from_iida_json(cls, path: str | Path) -> "CausalTopology":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_iida_topology(data)

    @classmethod
    def from_iida_topology(cls, data: dict) -> "CausalTopology":
        topology = cls(graph=nx.DiGraph())
        physical = data.get("network-model", {}).get("physical-layer", {})

        for device in physical.get("device", []):
            device_id = device["device-id"]
            device_object = device_object_id(device_id)
            topology.devices.add(device_id)
            topology.graph.add_node(
                device_object,
                object_type="device",
                device_id=device_id,
                role=device.get("role", "other"),
                node_monitor_enabled=bool(device.get("node-monitor-enabled", False)),
            )
            if loopback := device.get("loopback"):
                topology.device_addresses[loopback.split("/", 1)[0]] = device_id
            for interface in device.get("interface", []):
                interface_id = interface["interface-id"]
                interface_object = interface_object_id(device_id, interface_id)
                topology.interfaces[(device_id, interface_id)] = interface_object
                topology.graph.add_node(
                    interface_object,
                    object_type="interface",
                    device_id=device_id,
                    interface_id=interface_id,
                )
                topology.graph.add_edge(device_object, interface_object, relation="owns")
                if address := interface.get("ip-address"):
                    topology.device_addresses[address.split("/", 1)[0]] = device_id

        for connection in physical.get("physical-connection", []):
            endpoints = [_parse_endpoint(connection, endpoint) for endpoint in connection.get("endpoint", [])]
            if len(endpoints) != 2:
                raise ValueError(f"physical-connection must have exactly two endpoints: {connection!r}")
            _add_physical_link(topology, endpoints[0], endpoints[1], connection.get("connection-id"))

        l3 = data.get("network-model", {}).get("layer3-layer", {})
        for session in l3.get("bgp-session", []):
            endpoints = [endpoint.get("device-id") for endpoint in session.get("endpoint", [])]
            if len(endpoints) != 2 or any(endpoint not in topology.devices for endpoint in endpoints):
                continue
            session_object = bgp_session_object_id(session.get("session-id") or "--".join(sorted(endpoints)))
            topology.bgp_sessions[frozenset(endpoints)] = session_object
            topology.graph.add_node(
                session_object,
                object_type="bgp-session",
                session_id=session.get("session-id"),
                bgp_type=session.get("type", "ebgp"),
                devices=tuple(endpoints),
            )
            for device_id in endpoints:
                topology.graph.add_edge(device_object_id(device_id), session_object, relation="device-affects-session")
            for link_object in topology.links_between(endpoints[0], endpoints[1]):
                topology.graph.add_edge(link_object, session_object, relation="link-affects-session")

        return topology

    def object_type(self, object_id: str) -> str:
        return str(self.graph.nodes.get(object_id, {}).get("object_type", "unknown"))

    def object_devices(self, object_id: str) -> tuple[str, ...]:
        attrs = self.graph.nodes.get(object_id, {})
        if device_id := attrs.get("device_id"):
            return (str(device_id),)
        return tuple(str(device_id) for device_id in attrs.get("devices", ()))

    def device_object(self, device_id: str) -> str | None:
        object_id = device_object_id(device_id)
        return object_id if object_id in self.graph else None

    def interface_object(self, device_id: str, interface_id: str) -> str | None:
        return self.interfaces.get((device_id, interface_id))

    def physical_link_for_interface(self, device_id: str, interface_id: str) -> str | None:
        return self.interface_links.get((device_id, interface_id))

    def bgp_session_for_devices(self, device_a: str, device_b: str) -> str | None:
        return self.bgp_sessions.get(frozenset({device_a, device_b}))

    def resolve_device_by_address(self, address: str) -> str | None:
        return self.device_addresses.get(address)

    def links_between(self, device_a: str, device_b: str) -> list[str]:
        links: list[str] = []
        for object_id, attrs in self.graph.nodes(data=True):
            if attrs.get("object_type") != "physical-link":
                continue
            if {device_a, device_b}.issubset(set(attrs.get("devices", ()))):
                links.append(object_id)
        return links

    def objects_by_type(self, object_type: str) -> list[str]:
        return [
            object_id for object_id, attrs in self.graph.nodes(data=True)
            if attrs.get("object_type") == object_type
        ]


def device_object_id(device_id: str) -> str:
    return f"Device:{device_id}"


def interface_object_id(device_id: str, interface_id: str) -> str:
    return f"Interface:{device_id}:{interface_id}"


def normalize_interface_id(interface_id: str) -> str:
    normalized = interface_id.strip()
    replacements = (
        ("GigabitEthernet", "GE"),
        ("TenGigabitEthernet", "TE"),
        ("FastEthernet", "FE"),
        ("Ethernet", "E"),
    )
    for long_name, short_name in replacements:
        if normalized.startswith(long_name):
            return short_name + normalized[len(long_name):]
    return normalized


def physical_link_object_id(endpoint_a: InterfaceEndpoint, endpoint_b: InterfaceEndpoint) -> str:
    left, right = sorted([
        f"{endpoint_a.device_id}:{endpoint_a.interface_id}",
        f"{endpoint_b.device_id}:{endpoint_b.interface_id}",
    ])
    return f"PhysicalLink:{left}--{right}"


def bgp_session_object_id(session_id: str) -> str:
    return f"BGPSession:{session_id}"


def _parse_endpoint(connection: dict, endpoint: dict) -> InterfaceEndpoint:
    connection_id = connection.get("connection-id", "<unknown>")
    device_id = endpoint.get("device-id")
    interface_id = endpoint.get("interface-id")
    if not device_id or not interface_id:
        raise ValueError(f"physical-connection {connection_id} requires device-id and interface-id")
    return InterfaceEndpoint(device_id=device_id, interface_id=interface_id)


def _add_physical_link(
    topology: CausalTopology,
    endpoint_a: InterfaceEndpoint,
    endpoint_b: InterfaceEndpoint,
    connection_id: str | None,
) -> None:
    link_object = physical_link_object_id(endpoint_a, endpoint_b)
    endpoints = (endpoint_a, endpoint_b)
    for endpoint in endpoints:
        if endpoint.device_id not in topology.devices:
            raise ValueError(f"physical-connection {connection_id} references unknown device {endpoint.device_id}")
        if (endpoint.device_id, endpoint.interface_id) not in topology.interfaces:
            raise ValueError(
                f"physical-connection {connection_id} references unknown interface "
                f"{endpoint.device_id}:{endpoint.interface_id}"
            )

    topology.graph.add_node(
        link_object,
        object_type="physical-link",
        connection_id=connection_id,
        endpoints=tuple(f"{endpoint.device_id}:{endpoint.interface_id}" for endpoint in endpoints),
        devices=tuple(endpoint.device_id for endpoint in endpoints),
    )
    for endpoint in endpoints:
        interface_object = topology.interfaces[(endpoint.device_id, endpoint.interface_id)]
        topology.interface_links[(endpoint.device_id, endpoint.interface_id)] = link_object
        topology.graph.add_edge(interface_object, link_object, relation="can-fail-link")
        topology.graph.add_edge(link_object, interface_object, relation="affects-interface")
        topology.graph.add_edge(device_object_id(endpoint.device_id), link_object, relation="device-affects-link")
    upstream, downstream = _ordered_device_pair(topology, endpoint_a.device_id, endpoint_b.device_id)
    if upstream != downstream:
        topology.graph.add_edge(device_object_id(upstream), device_object_id(downstream), relation="device-affects-device")


def _ordered_device_pair(topology: CausalTopology, device_a: str, device_b: str) -> tuple[str, str]:
    role_a = topology.graph.nodes[device_object_id(device_a)].get("role", "other")
    role_b = topology.graph.nodes[device_object_id(device_b)].get("role", "other")
    priority_a = _ROLE_PRIORITY.get(str(role_a), _ROLE_PRIORITY["other"])
    priority_b = _ROLE_PRIORITY.get(str(role_b), _ROLE_PRIORITY["other"])
    if priority_a < priority_b:
        return device_a, device_b
    if priority_b < priority_a:
        return device_b, device_a
    return tuple(sorted((device_a, device_b)))