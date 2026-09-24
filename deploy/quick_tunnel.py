"""Optional short-lived HTTPS access to the loopback setup wizard.

cloudflared is downloaded from an official GitHub release with the release's
SHA-256 digest. The quick tunnel exists only while the setup process runs.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


RELEASE_API = 'https://api.github.com/repos/cloudflare/cloudflared/releases/latest'
ASSET = 'cloudflared-linux-amd64'
OWN_BINARY = Path('/usr/local/bin/heimdall-cloudflared')
URL = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com(?=$|[\s/])')


class TunnelError(RuntimeError):
    pass


def find_url(text: str) -> str | None:
    match = URL.search(text)
    return match.group(0) if match else None


def _json(url: str) -> dict:
    request = urllib.request.Request(url, headers={'User-Agent': 'Heimdall-Nexus-Installer/1.0',
                                                   'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def ensure_binary() -> str:
    existing = shutil.which('cloudflared') or (str(OWN_BINARY) if OWN_BINARY.is_file() else None)
    if existing:
        return existing
    release = _json(RELEASE_API)
    asset = next((item for item in release.get('assets', []) if item.get('name') == ASSET), None)
    if not asset or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(asset.get('digest') or '')):
        raise TunnelError('Cloudflare release did not include a verified Linux binary.')
    url = str(asset.get('browser_download_url') or '')
    if not url.startswith('https://github.com/cloudflare/cloudflared/releases/download/'):
        raise TunnelError('Cloudflare release returned an unexpected download address.')
    expected = asset['digest'].split(':', 1)[1]
    OWN_BINARY.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix='.heimdall-cloudflared-', dir=OWN_BINARY.parent)
    digest = hashlib.sha256()
    total = 0
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'Heimdall-Nexus-Installer/1.0'})
        with os.fdopen(fd, 'wb') as output, urllib.request.urlopen(request, timeout=90) as response:
            for block in iter(lambda: response.read(256 * 1024), b''):
                total += len(block)
                if total > 80 * 1024 * 1024:
                    raise TunnelError('Cloudflare binary was larger than expected.')
                digest.update(block)
                output.write(block)
        if digest.hexdigest() != expected:
            raise TunnelError('Cloudflare binary checksum did not match its release metadata.')
        os.chmod(temp_name, 0o755)
        os.replace(temp_name, OWN_BINARY)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return str(OWN_BINARY)


def start(port: int, *, binary: str | None = None, timeout: int = 60) -> tuple[subprocess.Popen, str]:
    executable = binary or ensure_binary()
    command = [executable, 'tunnel', '--no-autoupdate', '--url',
               f'http://127.0.0.1:{port}', '--loglevel', 'info']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)
    messages: queue.Queue[str | None] = queue.Queue(maxsize=64)

    def read_output():
        assert process.stdout is not None
        for line in process.stdout:
            try:
                messages.put_nowait(line)
            except queue.Full:
                pass
        try:
            messages.put_nowait(None)
        except queue.Full:
            pass

    threading.Thread(target=read_output, name='heimdall-tunnel-output', daemon=True).start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = messages.get(timeout=0.5)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if line is None:
            break
        url = find_url(line)
        if url:
            return process, url
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    raise TunnelError('Cloudflare could not create a temporary HTTPS link. Use SSH forwarding instead.')


def reachable(url: str, *, timeout: float = 60, pause: float = 2) -> bool:
    """True once the public link reaches this wizard, not a Cloudflare error page.

    The wizard answers an unauthenticated request with 401 and its own JSON.
    Printing the link before this succeeds sends users to an address that may
    not resolve yet, and a failed DNS lookup can then stay cached for minutes.
    """
    deadline = time.monotonic() + timeout
    request = urllib.request.Request(url + '/', headers={'User-Agent': 'Heimdall-Nexus-Installer/1.0'})
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(request, timeout=8).close()
        except urllib.error.HTTPError as error:
            body = error.read(2048)
            if error.code == 401 and b'one-time URL' in body:
                return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(pause)
    return False


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def start_verified(port: int, *, attempts: int = 3, binary: str | None = None,
                   verify_timeout: float = 60, log=print) -> tuple[subprocess.Popen, str]:
    """Create a quick tunnel and return it only after the link answers."""
    executable = binary or ensure_binary()
    last = 'Cloudflare did not create a link.'
    for attempt in range(1, attempts + 1):
        try:
            process, url = start(port, binary=executable)
        except TunnelError as error:
            last = str(error)
        else:
            log(f'Checking the temporary link ({attempt}/{attempts})…')
            if reachable(url, timeout=verify_timeout):
                return process, url
            stop(process)
            last = 'The temporary link was created but did not answer in time.'
        if attempt < attempts:
            log(f'{last} Trying again…')
            time.sleep(3)
    raise TunnelError(last)
