from __future__ import annotations

from src.plotter_backend.machine import grbl_transport


def test_parse_tcp_endpoint_accepts_scheme_and_host_port() -> None:
    assert grbl_transport.parse_tcp_endpoint("tcp://192.168.1.50:23") == grbl_transport.TcpEndpoint("192.168.1.50", 23)
    assert grbl_transport.parse_tcp_endpoint("192.168.1.50:8080") == grbl_transport.TcpEndpoint("192.168.1.50", 8080)
    assert grbl_transport.parse_tcp_endpoint("wifi://plotter.local") == grbl_transport.TcpEndpoint("plotter.local", 23)


def test_parse_tcp_endpoint_leaves_com_ports_as_serial() -> None:
    assert grbl_transport.parse_tcp_endpoint("COM6") is None
    assert not grbl_transport.is_tcp_endpoint("COM11")
