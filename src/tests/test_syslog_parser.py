from topology_syslog.ingestion.syslog_parser import parse


def test_rfc3164_hostname_and_pri():
    raw = b"<34>Aug 15 10:00:00 Core-Router1 %LINK-3-UPDOWN: Interface GE0/0 down"
    msg = parse(raw, "192.168.1.1")
    assert msg.hostname == "Core-Router1"
    assert msg.facility == 4   # 34 >> 3
    assert msg.severity == 2   # 34 & 7


def test_rfc3164_cisco_event_type():
    raw = b"<34>Aug 15 10:00:00 Core-Router1 %LINK-3-UPDOWN: Interface GE0/0 down"
    msg = parse(raw, "192.168.1.1")
    assert msg.event_type == "%LINK-3-UPDOWN"


def test_rfc3164_no_cisco_event():
    raw = b"<34>Aug 15 10:00:00 router1 kernel: eth0 entered promiscuous mode"
    msg = parse(raw, "10.0.0.1")
    assert msg.event_type is None


def test_rfc5424_hostname_and_pri():
    raw = b"<165>1 2026-08-15T10:00:00Z Core-Router1 myapp 1234 ID47 - test message"
    msg = parse(raw, "10.0.0.1")
    assert msg.hostname == "Core-Router1"
    assert msg.facility == 20  # 165 >> 3
    assert msg.severity == 5   # 165 & 7


def test_rfc5424_dash_hostname_falls_back_to_source_ip():
    raw = b"<165>1 2026-08-15T10:00:00Z - myapp 1234 ID47 - test"
    msg = parse(raw, "10.1.2.3")
    assert msg.hostname == "10.1.2.3"


def test_rfc5424_message_body():
    raw = b"<34>1 2026-08-15T10:00:00Z router1 app - - - %BGP-5-ADJCHANGE: neighbor down"
    msg = parse(raw, "10.0.0.1")
    assert "%BGP-5-ADJCHANGE" in msg.message
    assert msg.event_type == "%BGP-5-ADJCHANGE"


def test_fallback_on_invalid_format():
    raw = b"this is not a valid syslog message"
    msg = parse(raw, "10.0.0.99")
    assert msg.source_ip == "10.0.0.99"
    assert msg.hostname == "10.0.0.99"
    assert "not a valid syslog" in msg.message


def test_source_ip_recorded():
    raw = b"<34>Aug 15 10:00:00 router1 some message"
    msg = parse(raw, "172.16.0.1")
    assert msg.source_ip == "172.16.0.1"
