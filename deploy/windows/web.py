"""Caddy configuration for Windows: the same routes as deploy/nginx/heimdall-nexus.conf.template."""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape


def caddyfile(domain: str, web_root: Path, *, tls: bool, email: str = '') -> str:
    """With HTTPS, Caddy gets and renews the certificate and redirects HTTP."""
    # Without HTTPS, answer any name, like the Linux Nginx site (LAN IPs included).
    site = domain if tls else ':80'
    options = ['admin off']
    if tls and email:
        options.append(f'email {email}')
    else:
        options.append('auto_https off')
    root = str(web_root).replace('\\', '/')
    return f'''{{
\t{chr(10).join(options).replace(chr(10), chr(10) + chr(9))}
}}

{site} {{
\troot * "{root}"
\tencode gzip
\theader -Server

\t# Public Sagas reads: GET only, never cached.
\t@sagas path /api/sagas/v1/overview /api/sagas/v1/vikings/* /api/sagas/v1/atlas/*
\thandle @sagas {{
\t\t@write not method GET HEAD
\t\trespond @write 403
\t\theader Cache-Control "no-store"
\t\treverse_proxy 127.0.0.1:8791
\t}}

\tredir /jarl /jarl/ 301
\thandle /jarl/* {{
\t\treverse_proxy 127.0.0.1:8791
\t}}

\thandle {{
\t\t@json path *.json /assets/tema.css
\t\theader @json Cache-Control "no-cache"
\t\tfile_server
\t}}
}}
'''


def service_xml(caddy: Path, folder: Path, logs: Path) -> str:
    """WinSW definition of heimdall-web; Caddy keeps certificates in its own folder."""
    config = folder / 'Caddyfile'
    return f'''<service>
  <id>heimdall-web</id>
  <name>Heimdall Nexus - web server</name>
  <description>Caddy: the public site and the panel proxy.</description>
  <executable>{escape(str(caddy))}</executable>
  <arguments>run --config "{escape(str(config))}" --adapter caddyfile</arguments>
  <workingdirectory>{escape(str(folder))}</workingdirectory>
  <startmode>Automatic</startmode>
  <depend>heimdall-panel</depend>
  <stoptimeout>20 sec</stoptimeout>
  <logpath>{escape(str(logs))}</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>4</keepFiles>
  </log>
  <onfailure action="restart" delay="10 sec"/>
  <env name="XDG_DATA_HOME" value="{escape(str(folder / 'data'))}"/>
  <env name="XDG_CONFIG_HOME" value="{escape(str(folder / 'config'))}"/>
</service>
'''
