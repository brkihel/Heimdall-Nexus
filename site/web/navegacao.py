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
    return {'version': 3, 'style': 'discreto', 'palette': PALETTE.copy(),
            'known': order,
            'links': [{'id': key, 'label': LABELS.get(key, pages[key]['titulo']),
                       'visible': True, 'children': []} for key in order]}


def validate(value: object, manifest: dict) -> dict:
    pages = {page['id']: page for page in manifest['paginas'] if page.get('url')}
    if not isinstance(value, dict) or set(value) not in ({'version', 'style', 'links'},
                                                       {'version', 'style', 'links', 'palette'},
                                                       {'version', 'style', 'links', 'palette', 'known'}) or \
            type(value['version']) is not int or value['version'] not in (1, 2, 3) or \
            value['style'] not in STYLES or not isinstance(value['links'], list) or \
            len(value['links']) > 50:
        raise ValueError('configuração do menu inválida')
    known = value.get('known', list(pages))
    if not isinstance(known, list) or len(known) > 50 or \
            any(not isinstance(key, str) or key not in pages for key in known) or \
            len(set(known)) != len(known):
        raise ValueError('páginas conhecidas do menu inválidas')
    palette = value.get('palette', PALETTE)
    if not isinstance(palette, dict) or set(palette) != set(PALETTE) or any(
            not isinstance(color, str) or not COLOR.fullmatch(color)
            for color in palette.values()):
        raise ValueError('cores do menu inválidas')
    seen = set()

    def clean_link(link: object, *, child: bool = False) -> dict:
        fields = {'id', 'label', 'visible'}
        if value['version'] == 3 and not child:
            fields.add('children')
        if not isinstance(link, dict) or set(link) != fields or \
                not isinstance(link['id'], str) or link['id'] not in pages or \
                link['id'] in seen or not isinstance(link['label'], str) or \
                not LABEL.fullmatch(link['label'].strip()) or \
                not isinstance(link['visible'], bool):
            raise ValueError('link do menu inválido')
        seen.add(link['id'])
        result = {'id': link['id'], 'label': link['label'].strip(),
                  'visible': link['visible']}
        if not child:
            children = link.get('children', [])
            if not isinstance(children, list) or len(children) > 12:
                raise ValueError('submenus do menu inválidos')
            result['children'] = [clean_link(item, child=True) for item in children]
        return result

    links = [clean_link(item) for item in value['links']]
    if len(seen) > 50:
        raise ValueError('o menu aceita até 50 páginas')
    if (value['version'] == 1 and seen != set(pages)) or not seen <= set(known):
        raise ValueError('páginas do menu inválidas')
    return {'version': 3, 'style': value['style'], 'palette': palette,
            'known': known, 'links': links}


def load(base: Path, manifest: dict) -> dict:
    fallback = defaults(manifest)
    try:
        saved = json.loads((base / FILE).read_text(encoding='utf-8'))
        if not isinstance(saved, dict) or not isinstance(saved.get('links'), list):
            raise ValueError('configuração do menu inválida')
        present = {page['id'] for page in manifest['paginas'] if page.get('url')}
        pruned = []
        for item in saved['links']:
            if not isinstance(item, dict):
                continue
            if saved.get('version') == 3 and isinstance(item.get('children'), list):
                children = [child for child in item['children']
                            if isinstance(child, dict) and child.get('id') in present]
                if item.get('id') not in present:
                    pruned.extend({**child, 'children': []} for child in children)
                    continue
                item = {**item, 'children': children}
            if item.get('id') in present:
                pruned.append(item)
        saved = {**saved, 'links': pruned}
        if 'known' in saved:
            saved['known'] = [key for key in saved['known'] if key in present]
        listed = {item['id'] for item in saved['links']}
        listed.update(child['id'] for item in saved['links']
                      for child in item.get('children', []))
        old = validate(saved, {'paginas': [page for page in manifest['paginas']
                                           if page['id'] in (set(saved.get('known') or []) | listed)]})
    except (OSError, ValueError, TypeError, AttributeError):
        return fallback
    current = {item['id']: item for item in fallback['links']}
    links = [item for item in old['links'] if item['id'] in current]
    links += [item for item in fallback['links'] if item['id'] not in old['known']]
    return {'version': 3, 'style': old['style'], 'palette': old['palette'],
            'known': list(current), 'links': links}


def public(value: dict, manifest: dict, name: str = '') -> dict:
    pages = {page['id']: page['url'] for page in manifest['paginas'] if page.get('url')}
    return {'name': name[:60], 'style': value['style'], 'palette': value['palette'],
            'links': [{'label': link['label'], 'url': pages[link['id']],
                       'children': [{'label': child['label'], 'url': pages[child['id']]}
                                    for child in link['children']
                                    if child['visible'] and child['id'] in pages]}
                      for link in value['links'] if link['visible'] and link['id'] in pages]}
