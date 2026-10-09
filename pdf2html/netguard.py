"""Hard block on outbound network traffic for the whole process.

Same guard as rit-press-extractor's extractor/netguard.py. Converting runs
offline: once enable() runs, any attempt to open an internet connection (or
resolve a hostname) raises NetworkBlocked, so no part of an unpublished article
can leave the computer, even through a third-party library.
"""
from __future__ import annotations

import socket

_enabled = False
_AF_UNIX = getattr(socket, "AF_UNIX", None)  # missing on Windows


class NetworkBlocked(RuntimeError):
    pass


def _deny(*_args, **_kwargs):
    raise NetworkBlocked("Outbound network access is disabled in journal-pdf-to-html.")


def enable() -> None:
    global _enabled
    if _enabled:
        return
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto

    def connect(self, address):
        if _AF_UNIX is not None and self.family == _AF_UNIX:
            return real_connect(self, address)
        _deny()

    def connect_ex(self, address):
        if _AF_UNIX is not None and self.family == _AF_UNIX:
            return real_connect_ex(self, address)
        _deny()

    def sendto(self, *args):
        if _AF_UNIX is not None and self.family == _AF_UNIX:
            return real_sendto(self, *args)
        _deny()

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto
    socket.create_connection = _deny
    socket.getaddrinfo = _deny
    socket.gethostbyname = _deny
    socket.gethostbyname_ex = _deny
    _enabled = True


def is_enabled() -> bool:
    return _enabled
