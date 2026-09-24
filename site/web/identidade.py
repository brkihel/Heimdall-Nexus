#!/usr/bin/env python3
"""Site identity: name, slogan, footer, colors, logo, favicon and background.

identidade.json is the single source. Saving it rewrites the marked elements of
every page source (so the editor, previews and the public site agree) and
produces assets/tema.css, which each page loads after its own <style>, so the
color table overrides the page defaults.

Pages mark what belongs to the identity with data-identidade:

    <span data-identidade="nome">…</span>          text: site name
    <p data-identidade="slogan">…</p>              text: slogan
    <p data-identidade="rodape">…</p>              text: footer (line breaks kept)
    <img data-identidade="logo" hidden>            src: logo, hidden when none
    <link rel="icon" data-identidade="favicon">    href: favicon
    <meta property="og:site_name" data-identidade="nome" content="">
    <link rel="canonical" data-identidade="url" data-caminho="/wiki/">
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ARQUIVO = 'identidade.json'
MARCA_DIR = 'marca'

# Each color overrides a CSS variable that all pages already use.
CORES = [
    ('fundo', '--breu', 'Fundo da página', '#05090d'),
    ('fundo_2', '--noite', 'Fundo alternativo', '#080e14'),
    ('superficie', '--carvao', 'Cartões e painéis', '#0d151d'),
    ('superficie_2', '--ardosia', 'Cartões em destaque', '#152029'),
    ('borda', '--borda', 'Bordas', '#22313d'),
    ('borda_forte', '--borda-viva', 'Bordas em foco', '#33475a'),
    ('titulo', '--osso', 'Títulos', '#e6e0d2'),
    ('texto', '--texto', 'Texto', '#b4bec7'),
    ('texto_fraco', '--fraco', 'Texto secundário', '#78848f'),
    ('destaque', '--ouro', 'Cor de destaque', '#c8a45c'),
    ('destaque_claro', '--ouro-claro', 'Destaque claro', '#eeddb0'),
    ('destaque_escuro', '--ouro-fundo', 'Destaque escuro', '#7d6331'),
    ('brilho', '--brasa', 'Brilho (brasas, avisos)', '#ff8b3d'),
    ('brilho_claro', '--brasa-clara', 'Brilho claro', '#ffc477'),
]
PALETAS = {
    'Heimdall (padrão)': {k: v for k, _, _, v in CORES},
    'Gelo': {'fundo': '#060a10', 'fundo_2': '#0a111a', 'superficie': '#0f1823', 'superficie_2': '#16222f',
             'borda': '#223244', 'borda_forte': '#35506a', 'titulo': '#e8f1f8', 'texto': '#b7c6d3',
             'texto_fraco': '#7a8a99', 'destaque': '#7cc4e4', 'destaque_claro': '#cdeaf7',
             'destaque_escuro': '#2f6a86', 'brilho': '#9fe3ff', 'brilho_claro': '#dff6ff'},
    'Floresta': {'fundo': '#060906', 'fundo_2': '#0a100a', 'superficie': '#101810', 'superficie_2': '#172317',
                 'borda': '#243324', 'borda_forte': '#3a513a', 'titulo': '#e7eadc', 'texto': '#b9c2ae',
                 'texto_fraco': '#7d8a73', 'destaque': '#9cc26a', 'destaque_claro': '#dcecc0',
                 'destaque_escuro': '#4f6b2f', 'brilho': '#e0b24a', 'brilho_claro': '#f3d98b'},
    'Sangue': {'fundo': '#0a0506', 'fundo_2': '#10090a', 'superficie': '#190e10', 'superficie_2': '#231417',
               'borda': '#3a2226', 'borda_forte': '#5a333a', 'titulo': '#f1e3e0', 'texto': '#cdb8b6',
               'texto_fraco': '#8f7774', 'destaque': '#d0574a', 'destaque_claro': '#f2c1b9',
               'destaque_escuro': '#7a2b24', 'brilho': '#ff7a45', 'brilho_claro': '#ffc2a0'},
}
PADRAO = {
    'nome': 'Seu Servidor',
    'slogan': 'Escreva aqui o slogan do seu servidor',
    'rodape': 'Servidor comunitário de Valheim. Não somos afiliados à Iron Gate AB nem à Coffee Stain.',
    'url': '',
    'cores': PALETAS['Heimdall (padrão)'],
    'logo': '',
    'favicon': '/marca/favicon.svg',
    'fundo': '/assets/clareira-1600.webp',
}
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
ASSET = re.compile(r'^/(?:marca|assets)/[A-Za-z0-9._-]{1,80}$')
URL = re.compile(r'^https?://[A-Za-z0-9.-]+(?::\d{1,5})?$')


class IdentidadeErro(ValueError):
    pass


def carregar(base: Path) -> dict:
    data = {}
    try:
        data = json.loads((base / ARQUIVO).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    merged = {**PADRAO, **{k: v for k, v in data.items() if k in PADRAO}}
    merged['cores'] = {**PADRAO['cores'], **(data.get('cores') or {})}
    return merged


def validar(data: dict) -> dict:
    """Return a clean identity or raise IdentidadeErro with a readable reason."""
    out = {}
    for key, limit in (('nome', 60), ('slogan', 160), ('rodape', 400)):
        value = str(data.get(key, PADRAO[key])).strip()
        if len(value) > limit or any(ord(c) < 32 and c != '\n' for c in value):
            raise IdentidadeErro(f'{key} inválido (até {limit} caracteres)')
        out[key] = value
    if not out['nome']:
        raise IdentidadeErro('o nome do site não pode ficar vazio')
    url = str(data.get('url') or '').strip().rstrip('/')
    if url and not URL.fullmatch(url):
        raise IdentidadeErro('endereço do site inválido; use https://seu-dominio')
    out['url'] = url
    for key in ('logo', 'favicon', 'fundo'):
        value = str(data.get(key) or '').strip()
        if value and not ASSET.fullmatch(value):
            raise IdentidadeErro(f'{key}: caminho de arquivo inválido')
        out[key] = value
    cores = {}
    for key, _, label, default in CORES:
        value = str((data.get('cores') or {}).get(key, default)).strip()
        if not HEX.fullmatch(value):
            raise IdentidadeErro(f'cor inválida em {label}: use #RRGGBB')
        cores[key] = value.lower()
    out['cores'] = cores
    return out


def tema_css(ident: dict) -> str:
    lines = ['/* Generated from identidade.json by the panel. Edit colors in the panel. */', ':root{']
    for key, var, _, default in CORES:
        lines.append(f'  {var}:{ident["cores"].get(key, default)};')
    fundo = ident.get('fundo')
    lines.append(f"  --imagem-fundo:{('url(' + json.dumps(fundo) + ')') if fundo else 'none'};")
    lines.append('}')
    return '\n'.join(lines) + '\n'


_START = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*\bdata-identidade="([a-z-]+)"[^>]*>')
_ATTR = re.compile(r'\s([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*("[^"]*"|\'[^\']*\'|[^\s"\'>]+))?')


def _set_attr(tag: str, name: str, value: str | None) -> str:
    """Set (or remove, when value is None) one attribute of a start tag."""
    pattern = re.compile(r'\s' + re.escape(name) + r'(?:\s*=\s*("[^"]*"|\'[^\']*\'|[^\s"\'>]+))?(?=[\s/>])')
    tag = pattern.sub('', tag)
    if value is None:
        return tag
    end = len(tag) - (2 if tag.endswith('/>') else 1)
    return f'{tag[:end]} {name}="{html.escape(value, quote=True)}"{tag[end:]}'


def _attr(tag: str, name: str) -> str | None:
    for match in _ATTR.finditer(tag):
        if match.group(1) == name:
            raw = match.group(2) or ''
            return html.unescape(raw.strip('"\''))
    return None


def aplicar(source: str, ident: dict) -> str:
    """Rewrite every data-identidade element of one page source."""
    out, pos = [], 0
    for match in _START.finditer(source):
        if match.start() < pos:
            continue
        name, role = match.group(1).lower(), match.group(2)
        tag = match.group(0)
        out.append(source[pos:match.start()])
        pos = match.end()
        if name == 'meta':
            if role in ('nome', 'slogan'):
                tag = _set_attr(tag, 'content', ident[role])
            elif role == 'url':
                caminho = _attr(tag, 'data-caminho') or '/'
                tag = _set_attr(tag, 'content', (ident['url'] + caminho) if ident.get('url') else caminho)
        elif name == 'link':
            if role == 'favicon':
                tag = _set_attr(tag, 'href', ident.get('favicon') or '/marca/favicon.svg')
                kind = {'svg': 'image/svg+xml', 'png': 'image/png', 'ico': 'image/x-icon',
                        'webp': 'image/webp'}.get((ident.get('favicon') or '.svg').rsplit('.', 1)[-1].lower())
                tag = _set_attr(tag, 'type', kind)
            elif role == 'url':
                caminho = _attr(tag, 'data-caminho') or '/'
                tag = _set_attr(tag, 'href', (ident['url'] + caminho) if ident.get('url') else caminho)
        elif name == 'img' and role == 'logo':
            tag = _set_attr(tag, 'src', ident.get('logo') or '')
            tag = _set_attr(tag, 'alt', ident['nome'])
            tag = _set_attr(tag, 'hidden', None if ident.get('logo') else '')
        elif role in ('nome', 'slogan', 'rodape'):
            close = source.find(f'</{name}>', pos)
            if close < 0:
                out.append(tag)
                continue
            text = html.escape(ident[role])
            if role == 'rodape':
                text = text.replace('\n', '<br>')
            out.append(tag + text)
            pos = close
            continue
        out.append(tag)
    out.append(source[pos:])
    return ''.join(out)


if __name__ == '__main__':
    import sys
    base = Path(__file__).parent
    if '--css' in sys.argv:
        print(tema_css(carregar(base)), end='')
    else:
        print(json.dumps(carregar(base), ensure_ascii=False, indent=2))
