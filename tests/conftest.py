"""Shared fixtures. No test may use the internet: an autouse fixture makes any attempt fail."""

import socket

import pytest

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver", None, ""}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address, *args):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOCAL_HOSTS:
            raise RuntimeError(f"a test tried to reach the network: {address!r}")
        return real_connect(self, address, *args)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host not in _LOCAL_HOSTS:
            raise RuntimeError(f"a test tried to resolve a network host: {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
