"""Validated, editable public-site navigation shared by every page."""
from __future__ import annotations

import json
import re
from pathlib import Path

FILE = 'navegacao.json'
STYLES = {'discreto', 'destaque', 'personalizado'}
PALETTE = {'background': '#080e14', 'text': '#b4bec7', 'accent': '#c8a45c'}
COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')
DEFAULT_ORDER = ('inicio', 'wiki', 'mapa', 'historias', 'armaria', 'rankings')
LABELS = {'inicio': 'Início', 'wiki': 'Wiki', 'mapa': 'Mapa',
          'historias': 'Histórias', 'armaria': 'Armaria', 'rankings': 'Rankings'}
LABEL = re.compile(r'^[^\x00-\x1f\x7f<>]{1,28}$')


def defaults(manifest: dict) -> dict:
    pages = {page['id']: page for page in manifest['paginas'] if page.get('url')}
    order = [*filter(pages.__contains__, DEFAULT_ORDER),
             *sorted(set(pages) - set(DEFAULT_ORDER))]
    return {'version': 1, 'style': 'discreto', 'palette': PALETTE.copy(),
            'links': [{'id': key, 'label': LABELS.get(key, pages[key]['titulo']),
                       'visible': True} for key in order]}


def validate(value: object, manifest: dict) -> dict:
    pages = {page['id']: page for page in manifest['paginas'] if page.get('url')}
    if not isinstance(value, dict) or set(value) not in ({'version', 'style', 'links'},
                                                       {'version', 'style', 'links', 'palette'}) or \
            type(value['version']) is not int or value['version'] != 1 or \
            value['style'] not in STYLES or not isinstance(value['links'], list) or \
            len(value['links']) > 50:
        raise ValueError('configuração do menu inválida')
    palette = value.get('palette', PALETTE)
    if not isinstance(palette, dict) or set(palette) != set(PALETTE) or any(
            not isinstance(color, str) or not COLOR.fullmatch(color)
            for color in palette.values()):
        raise ValueError('cores do menu inválidas')
    seen = set()
    links = []
    for link in value['links']:
        if not isinstance(link, dict) or set(link) != {'id', 'label', 'visible'} or \
                not isinstance(link['id'], str) or link['id'] not in pages or \
                link['id'] in seen or not isinstance(link['label'], str) or \
                not LABEL.fullmatch(link['label'].strip()) or \
                not isinstance(link['visible'], bool):
            raise ValueError('link do menu inválido')
        seen.add(link['id'])
        links.append({'id': link['id'], 'label': link['label'].strip(),
                      'visible': link['visible']})
    if seen != set(pages):
        raise ValueError('o menu precisa listar todas as páginas do site')
    return {'version': 1, 'style': value['style'], 'palette': palette, 'links': links}


def load(base: Path, manifest: dict) -> dict:
    fallback = defaults(manifest)
    try:
        saved = json.loads((base / FILE).read_text(encoding='utf-8'))
        if not isinstance(saved, dict) or not isinstance(saved.get('links'), list):
            raise ValueError('configuração do menu inválida')
        present = {page['id'] for page in manifest['paginas']}
        saved = {**saved, 'links': [item for item in saved['links']
                                   if isinstance(item, dict) and item.get('id') in present]}
        old = validate(saved, {'paginas': [page for page in manifest['paginas']
                                           if page['id'] in {x['id'] for x in saved['links']}]})
    except (OSError, ValueError, TypeError, AttributeError):
        return fallback
    current = {item['id']: item for item in fallback['links']}
    links = [item for item in old['links'] if item['id'] in current]
    links += [item for item in fallback['links'] if item['id'] not in {x['id'] for x in links}]
    return {'version': 1, 'style': old['style'], 'palette': old['palette'], 'links': links}


def public(value: dict, manifest: dict) -> dict:
    pages = {page['id']: page['url'] for page in manifest['paginas'] if page.get('url')}
    return {'style': value['style'], 'palette': value['palette'],
            'links': [{'label': link['label'], 'url': pages[link['id']]}
                      for link in value['links'] if link['visible'] and link['id'] in pages]}
