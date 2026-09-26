"""Authenticated loopback channel between the panel and the executor (Windows).

Both sides prove they know a secret file that only SYSTEM, administrators and
the panel's service account can read. The proof is an HMAC over fresh nonces
from both sides, so the secret never crosses the wire and a program that grabs
the port first learns nothing it could replay. Pure Python, so it is tested on
any system.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import socket
import socketserver
from pathlib import Path

GREETING = b'HEIMDALL-EXECUTOR 1 '
LOOPBACK = ('127.0.0.1', 'localhost', '::1')


def read_key(path: Path) -> bytes:
    key = Path(path).read_bytes().strip()
    if len(key) < 32:
        raise OSError('executor key is missing or too short')
    return key


def proof(key: bytes, role: bytes, first: bytes, second: bytes) -> bytes:
    return hmac.new(key, role + b':' + first + b':' + second, hashlib.sha256).hexdigest().encode()


def readline(connection: socket.socket, limit: int = 256) -> bytes:
    data = b''
    while not data.endswith(b'\n'):
        chunk = connection.recv(1)
        if not chunk:
            raise ConnectionError('closed during handshake')
        data += chunk
        if len(data) > limit:
            raise ConnectionError('handshake line too long')
    return data[:-1]


def parse_address(address) -> tuple[str, int]:
    host, _, port = str(address).rpartition(':')
    if host not in LOOPBACK:
        raise ValueError('the executor only listens on the loopback address')
    return host, int(port)


class LoopbackExecutorServer(socketserver.ThreadingTCPServer):
    """A connection reaches the handler only after the mutual proof."""
    daemon_threads = True
    allow_reuse_address = False  # a second executor must fail, not share the port

    def __init__(self, address, handler, key_file: Path):
        self.key = read_key(key_file)
        super().__init__(parse_address(address), handler)

    def finish_request(self, request, client_address):
        try:
            request.settimeout(10)
            server_nonce = secrets.token_hex(16).encode()
            request.sendall(GREETING + server_nonce + b'\n')
            client_proof, _, client_nonce = readline(request).partition(b' ')
            if not re.fullmatch(rb'[0-9a-f]{32}', client_nonce) or not hmac.compare_digest(
                    client_proof, proof(self.key, b'client', server_nonce, client_nonce)):
                return
            request.sendall(proof(self.key, b'server', client_nonce, server_nonce) + b'\n')
            request.settimeout(None)
        except (OSError, ConnectionError):
            return
        self.RequestHandlerClass(request, client_address, self)


def connect(address, timeout: float, key_file: Path) -> socket.socket:
    key = read_key(key_file)
    connection = socket.create_connection(parse_address(address), timeout=timeout)
    try:
        greeting = readline(connection)
        if not greeting.startswith(GREETING):
            raise ConnectionError('not the Heimdall executor')
        server_nonce = greeting[len(GREETING):]
        if not re.fullmatch(rb'[0-9a-f]{32}', server_nonce):
            raise ConnectionError('malformed greeting')
        client_nonce = secrets.token_hex(16).encode()
        connection.sendall(proof(key, b'client', server_nonce, client_nonce) + b' ' + client_nonce + b'\n')
        if not hmac.compare_digest(readline(connection), proof(key, b'server', client_nonce, server_nonce)):
            raise ConnectionError('the executor could not prove its identity')
    except BaseException:
        connection.close()
        raise
    return connection
