#!/usr/bin/env python3
"""Publish the site sources into HEIMDALL_WEB_DIR (default /srv/heimdall-web).

    sudo ./publicar.py                 # everything
    sudo ./publicar.py inicio wiki     # only these targets
    sudo ./publicar.py --retirar /guia/   # unpublish a removed page

Targets are the page ids of site-pages.json plus: vivo, modpack-ui, mods, tema,
marca, assets, sitemap and robots. Files are copied to a temporary name and
swapped in, so a reader never gets half a file; the previous version is kept
under HEIMDALL_WEB_BACKUP_DIR.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pwd
import re
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import identidade  # noqa: E402
import navegacao  # noqa: E402

DESTINO = Path(os.environ.get('HEIMDALL_WEB_DIR', '/srv/heimdall-web'))
BACKUP = Path(os.environ.get('HEIMDALL_WEB_BACKUP_DIR', '/var/backups/heimdall-web'))
URL_PAGINA = re.compile(r'^/(?:[a-z0-9-]{1,40}/){0,3}$')
FIXOS = {
    'vivo': ('assets/vivo.js', 'assets/vivo.js'),
    'modpack-ui': ('assets/modpack.js', 'assets/modpack.js'),
    'mods': ('mods.json', 'mods.json'),
    'cronicas': ('cronicas.html', 'cronicas/index.html'),
}


def public_html(source: str, path: str) -> str:
    """Add the shared menu without changing the instance's editable source."""
    def asset(name: str) -> str:
        digest = hashlib.sha256((BASE / 'assets' / name).read_bytes()).hexdigest()[:10]
        return f'/assets/{name}?v={digest}'
    if '/assets/navegacao.js' not in source:
        source = source.replace('</head>', f'<link rel="stylesheet" href="{asset("navegacao.css")}">\n'
                                f'<script src="{asset("navegacao.js")}" defer></script>\n</head>', 1)
    if path == 'index.html' and '/assets/sagas-resumo.js' not in source:
        source = source.replace('</head>', f'<link rel="stylesheet" href="{asset("sagas-resumo.css")}">\n'
                                f'<script src="{asset("sagas-resumo.js")}" defer></script>\n</head>', 1)
    return source


def saida_da_url(url: str) -> str:
    if not URL_PAGINA.fullmatch(url):
        raise SystemExit(f'endereço de página inválido: {url!r}')
    return url.lstrip('/') + 'index.html'


def paginas() -> dict[str, tuple[str, str]]:
    manifest = json.loads((BASE / 'site-pages.json').read_text(encoding='utf-8'))
    out = {}
    for page in manifest['paginas']:
        if page.get('url'):
            out[page['id']] = (page['fonte'], saida_da_url(page['url']))
    return out


class Publicador:
    def __init__(self):
        self.www = pwd.getpwnam(os.environ.get('HEIMDALL_WEB_USER', 'www-data'))
        self.carimbo = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.guardou = False

    def _dono(self, path: Path, mode: int):
        os.chown(path, self.www.pw_uid, self.www.pw_gid)
        os.chmod(path, mode)

    def _pasta(self, pasta: Path):
        pasta.mkdir(parents=True, exist_ok=True)
        while pasta != DESTINO and DESTINO in pasta.parents:
            self._dono(pasta, 0o755)
            pasta = pasta.parent

    def _guardar(self, destino: Path, caminho: str):
        if destino.exists():
            guarda = BACKUP / self.carimbo / caminho
            guarda.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destino, guarda)
            self.guardou = True

    def escrever(self, caminho: str, dados: bytes, rotulo: str):
        destino = DESTINO / caminho
        self._pasta(destino.parent)
        if destino.exists() and destino.read_bytes() == dados:
            return
        self._guardar(destino, caminho)
        temporario = destino.parent / f'.{destino.name}.novo'
        temporario.write_bytes(dados)
        self._dono(temporario, 0o644)
        os.replace(temporario, destino)
        print(f'{rotulo:10} → {destino} ({len(dados)} bytes)')

    def copiar_pasta(self, origem: Path, caminho: str, rotulo: str):
        if not origem.is_dir():
            return
        for arquivo in sorted(origem.rglob('*')):
            if arquivo.is_file() and not arquivo.name.startswith('.'):
                relativo = f'{caminho}/{arquivo.relative_to(origem).as_posix()}'
                self.escrever(relativo, arquivo.read_bytes(), rotulo)

    def retirar(self, url: str):
        caminho = saida_da_url(url)
        if caminho == 'index.html':
            raise SystemExit('a página inicial não pode ser retirada')
        destino = DESTINO / caminho
        if destino.exists():
            self._guardar(destino, caminho)
            destino.unlink()
            try:
                destino.parent.rmdir()
            except OSError:
                pass
            print(f'retirado   ← {destino}')


def sitemap(ident: dict, lista: dict) -> bytes:
    base = ident.get('url') or ''
    manifest = json.loads((BASE / 'site-pages.json').read_text(encoding='utf-8'))
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page in manifest['paginas']:
        if page['id'] in lista:
            linhas.append(f'  <url><loc>{base}{page["url"]}</loc></url>')
    linhas.append('</urlset>')
    return ('\n'.join(linhas) + '\n').encode()


def robots(ident: dict) -> bytes:
    texto = 'User-agent: *\nAllow: /\nDisallow: /jarl/\nDisallow: /api/\n'
    if ident.get('url'):
        texto += f'Sitemap: {ident["url"]}/sitemap.xml\n'
    return texto.encode()


def main(argv: list[str]) -> int:
    pub = Publicador()
    if argv[:1] == ['--retirar']:
        if len(argv) != 2:
            raise SystemExit('uso: publicar.py --retirar /endereco/')
        pub.retirar(argv[1])
        return 0
    lista = paginas()
    conhecidos = [*lista, *FIXOS, 'tema', 'marca', 'fontes', 'assets', 'navegacao', 'sitemap', 'robots']
    alvos = argv or conhecidos
    desconhecidos = [a for a in alvos if a not in conhecidos]
    if desconhecidos:
        print('não conheço:', ', '.join(desconhecidos), '\nconhecidos:', ', '.join(conhecidos))
        return 2
    ident = identidade.carregar(BASE)
    for alvo in alvos:
        if alvo in lista or alvo in FIXOS:
            origem, caminho = lista.get(alvo) or FIXOS[alvo]
            fonte = BASE / origem
            if not fonte.exists():
                print(f'!! {origem} não existe — pulei {alvo}')
                continue
            dados = fonte.read_bytes()
            if origem.endswith('.html'):
                source = identidade.aplicar(dados.decode('utf-8'), ident)
                dados = public_html(source, caminho).encode('utf-8')
            if origem.endswith('.html') and b'@@' in dados:
                print(f'!! {origem} ainda tem marcador @@ — não publiquei')
                return 1
            pub.escrever(caminho, dados, alvo)
        elif alvo == 'tema':
            pub.escrever('assets/tema.css', identidade.tema_css(ident).encode(), alvo)
        elif alvo == 'marca':
            pub.copiar_pasta(BASE / identidade.MARCA_DIR, 'marca', alvo)
        elif alvo == 'fontes':
            pub.copiar_pasta(BASE / 'assets/fontes', 'assets/fontes', alvo)
        elif alvo == 'assets':
            pub.copiar_pasta(BASE / 'assets', 'assets', alvo)
        elif alvo == 'navegacao':
            manifest = json.loads((BASE / 'site-pages.json').read_text(encoding='utf-8'))
            config = navegacao.public(navegacao.load(BASE, manifest), manifest)
            pub.escrever('assets/navegacao.json',
                         (json.dumps(config, ensure_ascii=False, separators=(',', ':')) + '\n').encode(), alvo)
        elif alvo == 'sitemap':
            pub.escrever('sitemap.xml', sitemap(ident, lista), alvo)
        elif alvo == 'robots':
            pub.escrever('robots.txt', robots(ident), alvo)
    if pub.guardou:
        print(f'backup em {BACKUP / pub.carimbo}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
