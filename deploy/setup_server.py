#!/usr/bin/env python3
"""Temporary, loopback-only browser wizard for a fresh Heimdall Nexus host."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import subprocess
import threading
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from installer import Choices, InstallError, Installer
import quick_tunnel


ASSETS = Path(__file__).with_name('setup')
CONTENT = {'/': ('index.html', 'text/html; charset=utf-8'),
           '/style.css': ('style.css', 'text/css; charset=utf-8'),
           '/app.js': ('app.js', 'application/javascript; charset=utf-8')}


class InstallState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.done = False
        self.step = 'welcome'
        self.messages: list[dict] = []
        self.error = ''
        self.result: dict = {}

    def report(self, step: str, message: str) -> None:
        with self.lock:
            self.step = step
            self.messages.append({'step': step, 'message': message})
            self.messages = self.messages[-240:]

    def begin(self) -> bool:
        with self.lock:
            if self.running or self.done:
                return False
            self.running = True
            self.error = ''
            self.messages = []
            self.result = {}
            self.step = 'starting'
            return True

    def finish(self, result: dict | None = None, error: str = '') -> None:
        with self.lock:
            self.running = False
            self.done = bool(result)
            self.error = error
            self.result = result or {}

    def snapshot(self) -> dict:
        with self.lock:
            return {'running': self.running, 'done': self.done,
                    'step': self.step, 'messages': list(self.messages),
                    'error': self.error, 'result': dict(self.result)}


class SetupServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, port: int):
        super().__init__(('127.0.0.1', port), SetupHandler)
        self.token = secrets.token_urlsafe(32)
        self.state = InstallState()
        self.public_origin: str | None = None


class SetupHandler(BaseHTTPRequestHandler):
    server: SetupServer

    def log_message(self, *_args):
        pass  # setup token and form content must never appear in an access log

    def _headers(self, status: HTTPStatus, content_type: str, length: int,
                 extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def _json(self, status: HTTPStatus, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self._headers(status, 'application/json; charset=utf-8', len(body))
        self.wfile.write(body)

    def _authorized(self) -> bool:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            value = cookie['heimdall_setup'].value
        except (KeyError, ValueError, CookieError):
            return False
        return hmac.compare_digest(value, self.server.token)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == '/claim':
            supplied = parse_qs(parsed.query).get('token', [''])[0]
            if not hmac.compare_digest(supplied, self.server.token):
                self._json(HTTPStatus.FORBIDDEN, {'error': 'Invalid one-time setup link.'})
                return
            secure = '; Secure' if self.server.public_origin and self.headers.get('Host') == urlsplit(self.server.public_origin).netloc else ''
            self._headers(HTTPStatus.SEE_OTHER, 'text/plain; charset=utf-8', 0,
                          {'Location': '/', 'Set-Cookie':
                           f'heimdall_setup={self.server.token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=7200{secure}'})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {'error': 'Open the one-time URL shown in the server terminal.'})
            return
        if parsed.path == '/api/state':
            self._json(HTTPStatus.OK, self.server.state.snapshot())
            return
        if parsed.path not in CONTENT:
            self._json(HTTPStatus.NOT_FOUND, {'error': 'Not found.'})
            return
        filename, content_type = CONTENT[parsed.path]
        content = (ASSETS / filename).read_bytes()
        self._headers(HTTPStatus.OK, content_type, len(content))
        self.wfile.write(content)

    def do_POST(self):
        if self.path != '/api/start':
            self._json(HTTPStatus.NOT_FOUND, {'error': 'Not found.'})
            return
        allowed = {f'http://127.0.0.1:{self.server.server_port}'}
        if self.server.public_origin:
            allowed.add(self.server.public_origin)
        if not self._authorized() or self.headers.get('Origin') not in allowed:
            self._json(HTTPStatus.FORBIDDEN, {'error': 'The setup session or browser origin is invalid.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 16_384:
                raise InstallError('The installation form is too large or empty.')
            data = json.loads(self.rfile.read(length))
            choices = Choices.parse(data)
        except (ValueError, json.JSONDecodeError, InstallError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return
        if not self.server.state.begin():
            self._json(HTTPStatus.CONFLICT, {'error': 'An installation is already running or complete.'})
            return
        state = self.server.state

        def worker():
            try:
                result = Installer(choices, state.report).run()
            except Exception as exc:  # surface the actionable error, keep secrets out of logs
                state.report('error', str(exc)[:400])
                state.finish(error=str(exc)[:400])
            else:
                state.finish(result=result)
                # The public setup link expires shortly after success.
                timer = threading.Timer(600, self.server.shutdown)
                timer.daemon = True
                timer.start()

        threading.Thread(target=worker, name='heimdall-install', daemon=False).start()
        self._json(HTTPStatus.ACCEPTED, {'started': True, 'summary': choices.public_summary()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--local-only', action='store_true', help='skip temporary public HTTPS link')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run the visual installer with sudo.')
    server = SetupServer(args.port)
    tunnel = None
    try:
        print(f'Heimdall Nexus setup is listening on this VPS at 127.0.0.1:{args.port}.', flush=True)
        if not args.local_only:
            print('Creating a temporary HTTPS link through Cloudflare…', flush=True)
            try:
                tunnel, server.public_origin = quick_tunnel.start(args.port)
            except (quick_tunnel.TunnelError, OSError) as error:
                print(f'Temporary link unavailable: {error}', flush=True)
        if server.public_origin:
            print('Open this temporary HTTPS link on your personal computer:', flush=True)
            print(f'{server.public_origin}/claim?token={server.token}', flush=True)
            print('The new address may take a few seconds to resolve in DNS.', flush=True)
            print('Cloudflare proxies this setup connection. The link closes when setup exits.', flush=True)
        else:
            print('Use SSH forwarding, then open this local link:', flush=True)
            print(f'http://127.0.0.1:{args.port}/claim?token={server.token}', flush=True)
            print(f'ssh -L {args.port}:127.0.0.1:{args.port} user@your-server', flush=True)
        print('Keep this terminal open until the installation finishes.', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if tunnel is not None and tunnel.poll() is None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()


if __name__ == '__main__':
    main()
