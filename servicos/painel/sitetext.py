"""Text fields of the public site, for the panel's Site tab and the in-page editor.

A page is split into its sections (the <section>, <header>, <nav> and <footer>
landmarks the page itself declares), and each section into text fields: the
smallest elements whose content is only text plus inline markup (a paragraph, a
heading, a list item, a button label). Layout, SVG, scripts and styles are never
exposed and never rewritten.

Every field is stamped in the canonical HTML with a data-campo="<token>"
attribute, which lets the in-page editor locate the source element for a clicked
paragraph. Fields without a token get one on the next save; until then they are
addressed by position.

Legacy build markers and values written by a page script are recognized. A live
value can be removed as an ordinary edit; a marker must be known to that page.

Saving replaces only the edited field's inner HTML and its style attribute, and
refuses if the field changed since it was read. Incoming HTML and CSS are
sanitized here, because this module runs inside the privileged executor and
must not trust the panel.

Which canonical HTML files exist and where each is published is declared by the
site itself in site-pages.json, so another site can ship its own list.
"""
import hashlib
import html
import json
import re
import secrets
from html.parser import HTMLParser
from pathlib import Path

MANIFEST = 'site-pages.json'
TOKEN_ATTR = 'data-campo'
TOKEN = re.compile(r'^[a-z0-9]{6,12}$')

# Never hold editable text; their content is skipped entirely.
OPAQUE = {'script', 'style', 'svg', 'noscript', 'template', 'textarea', 'select',
          'canvas', 'iframe', 'object', 'video', 'audio', 'picture', 'math'}
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
        'param', 'source', 'track', 'wbr'}
# Markup allowed inside a field. A field is an element whose whole subtree is
# made of these plus text.
INLINE = {'a', 'abbr', 'b', 'br', 'code', 'em', 'i', 'kbd', 'mark', 's', 'small',
          'span', 'strong', 'sub', 'sup', 'time', 'u'}
ALLOWED_ATTRS = {
    'span': {'data-vivo'},
    'a': {'href', 'target', 'rel', 'title'},
    'abbr': {'title'},
    'time': {'datetime'},
}
COMMON_ATTRS = {'class', 'id', 'style'}
SAFE_URL = re.compile(r'^(https?://|/|#|mailto:|@@[A-Z_]+@@)', re.I)
MARKER = re.compile(r'@@([A-Z_]+)@@')
HAS_WORD = re.compile(r'[^\W_]')
LIVE_KEY = re.compile(r'^[a-z][a-z_]{0,40}$')     # data-vivo="online": filled by /assets/vivo.js
LANDMARKS = {'section', 'header', 'footer', 'nav', 'aside'}
HEAD_META = {
    ('name', 'description'): 'Descrição (Google)',
    ('property', 'og:title'): 'Título ao compartilhar',
    ('property', 'og:description'): 'Descrição ao compartilhar',
    ('name', 'twitter:title'): 'Título no X/Twitter',
    ('name', 'twitter:description'): 'Descrição no X/Twitter',
}

# What the style toolbar may write. Anything else in a style attribute is dropped.
CSS_PROPERTIES = {
    'font-family', 'font-size', 'font-weight', 'font-style', 'text-decoration',
    'text-decoration-line', 'color', 'background-color', 'border', 'border-radius',
    'padding', 'text-shadow', 'box-shadow', 'letter-spacing', 'text-align',
    'line-height', 'text-transform',
}
CSS_VALUE = re.compile(r"^[#\w\s.,%()'\"+-]{1,200}$")
CSS_FORBIDDEN = re.compile(r'url|expression|javascript|import|\\|/\*|[<>]', re.I)


class TextError(Exception):
    """A request this module refuses, with a reason the panel can show."""


# ---------------------------------------------------------------- css
def clean_css(style: str) -> str:
    kept = []
    for declaration in (style or '').split(';'):
        if ':' not in declaration:
            continue
        name, value = declaration.split(':', 1)
        name, value = name.strip().lower(), value.strip()
        if name in CSS_PROPERTIES and value and CSS_VALUE.match(value) \
                and not CSS_FORBIDDEN.search(value):
            kept.append(f'{name}: {value}')
    return '; '.join(kept)


# ---------------------------------------------------------------- parsing
class _Node:
    __slots__ = ('tag', 'attrs', 'start', 'inner_start', 'inner_end', 'end',
                 'children', 'has_text', 'parent')

    def __init__(self, tag, attrs, start, inner_start, parent=None):
        self.tag, self.attrs, self.start, self.inner_start = tag, attrs, start, inner_start
        self.inner_end = self.end = None
        self.children = []
        self.has_text = False
        self.parent = parent


class _Tree(HTMLParser):
    """Element tree with exact offsets of each element, inner and outer."""

    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_starts = [0] + [m.end() for m in re.finditer('\n', source)]
        self.root = _Node('#root', {}, 0, 0)
        self.stack = [self.root]
        self.feed(source)
        self.close()
        for node in self.stack:
            node.inner_end = node.end = len(source)

    def _offset(self):
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def handle_starttag(self, tag, attrs):
        start = self._offset()
        inner = start + len(self.get_starttag_text())
        node = _Node(tag, dict(attrs), start, inner, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag in VOID:
            node.inner_end = node.end = inner
        else:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag and tag not in VOID:
            node = self.stack.pop()
            node.inner_end = node.end = node.inner_start

    def handle_endtag(self, tag):
        if not any(node.tag == tag for node in self.stack[1:]):
            return
        position = self._offset()
        after = self.source.find('>', position) + 1 or len(self.source)
        while len(self.stack) > 1:
            node = self.stack.pop()
            node.inner_end = position
            # An element closed implicitly ends where its parent's end tag starts.
            node.end = after if node.tag == tag else position
            if node.tag == tag:
                break

    def handle_data(self, data):
        if data.strip():
            self.stack[-1].has_text = True

    def handle_entityref(self, name):
        self.stack[-1].has_text = True

    def handle_charref(self, name):
        self.stack[-1].has_text = True


def _only_inline(node: _Node) -> bool:
    # An icon (svg) inside a heading is decoration: it stays, locked, and the text
    # around it is still a field.
    return all((child.tag in INLINE and _only_inline(child)) or child.tag == 'svg'
               for child in node.children)


def _any_text(node: _Node) -> bool:
    return node.has_text or any(_any_text(child) for child in node.children)


def _plain(fragment: str) -> str:
    text = re.sub(r'<[^>]*>', ' ', fragment)
    return re.sub(r'\s+', ' ', html.unescape(text)).strip()


def _digest(*parts: str) -> str:
    return hashlib.sha256('\0'.join(parts).encode('utf-8')).hexdigest()[:16]


def _live_ids(source: str) -> set[str]:
    """Ids that the page's scripts mention, quoted or as a #selector."""
    scripts = ' '.join(re.findall(r'<script\b[^>]*>(.*?)</script>', source, re.S | re.I))
    found = set()
    for element_id in set(re.findall(r'\sid\s*=\s*["\']([\w-]+)["\']', source)):
        if re.search(r'[\'"#]' + re.escape(element_id) + r'[\'"\s\]),.:]', scripts):
            found.add(element_id)
    return found


def _section_title(node: _Node, source: str) -> str | None:
    """The first heading inside a landmark names it in the panel."""
    stack = list(node.children)
    while stack:
        child = stack.pop(0)
        if child.tag in ('h1', 'h2', 'h3'):
            title = _plain(MARKER.sub('', source[child.inner_start:child.inner_end]))
            if title:
                return title
        if child.tag not in OPAQUE:
            stack[0:0] = child.children
    return None


def _kind(tag: str) -> str:
    if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        return 'titulo'
    if tag in ('a', 'button'):
        return 'botao'
    if tag == 'li':
        return 'item'
    return 'texto'


def _chip(kind: str, key: str, label: str) -> str:
    return f'<span data-{kind}="{html.escape(key, quote=True)}">{html.escape(label)}</span>'


def _markers_to_chips(fragment: str, labels: dict) -> str:
    """Markers in text become chips; markers inside a tag (an href) stay as they are."""
    parts = re.split(r'(<[^>]*>)', fragment)
    for index in range(0, len(parts), 2):
        parts[index] = MARKER.sub(
            lambda m: _chip('marker', m.group(1), labels.get(m.group(1), m.group(1))), parts[index])
    return ''.join(parts)


def _set_attr(start_tag: str, name: str, value: str | None) -> str:
    """The start tag with one attribute replaced, added or (value None) removed."""
    pattern = re.compile(rf'\s{re.escape(name)}\s*=\s*(["\']).*?\1', re.S)
    start_tag = pattern.sub('', start_tag)
    if value is None or value == '':
        return start_tag
    closing = '/>' if start_tag.endswith('/>') else '>'
    body = start_tag[:-len(closing)].rstrip()
    return f'{body} {name}="{html.escape(value, quote=True)}"{closing}'


def _field(node: _Node, source: str, live: set, labels: dict, position_id: str):
    raw = source[node.inner_start:node.inner_end]
    locks = []

    def find(parent):
        for child in parent.children:
            if child.attrs.get('id') in live or child.tag == 'svg':
                locks.append(child)
            else:
                find(child)

    find(node)
    editor, cursor, lock_html = [], node.inner_start, []
    for number, lock in enumerate(locks):
        editor.append(_markers_to_chips(source[cursor:lock.start], labels))
        outer = source[lock.start:lock.end]
        lock_html.append(outer)
        if lock.tag == 'svg':
            # Shown as itself, marked so it comes back from the file untouched.
            tag_end = lock.inner_start - lock.start
            editor.append(_set_attr(outer[:tag_end], 'data-lock', str(number)) + outer[tag_end:])
        else:
            editor.append(_chip('lock', str(number), _plain(outer) or '…'))
        cursor = lock.end
    editor.append(_markers_to_chips(source[cursor:node.inner_end], labels))

    free_text = raw
    for outer in lock_html:
        free_text = free_text.replace(outer, ' ')
    # Text inside data-vivo is painted by the page at run time, not written by anyone.
    free_text = re.sub(r'<span[^>]*\sdata-vivo="[^"]*"[^>]*>.*?</span>', ' ', free_text, flags=re.S)
    if node.attrs.get('data-vivo') is not None:
        return None
    if not HAS_WORD.search(MARKER.sub('', _plain(free_text))):
        return None
    token = node.attrs.get(TOKEN_ATTR) or ''
    style = node.attrs.get('style') or ''
    return {
        'id': position_id,
        'token': token if TOKEN.match(token) else '',
        'tipo': _kind(node.tag),
        'tag': node.tag,
        'html': ''.join(editor),
        'estilo': style,
        'travas': [lock.attrs.get('id') if lock.tag != 'svg' else None for lock in locks],
        'texto': _plain(raw),
        'hash': _digest(raw, style),
        '_raw': raw,
        '_span': (node.inner_start, node.inner_end),
        '_tag_span': (node.start, node.inner_start),
        '_locks': lock_html,
        '_markers': MARKER.findall(raw),
        '_node': node,
    }


def extract(source: str, labels: dict | None = None) -> list[dict]:
    """Sections with their fields, in page order."""
    labels = labels or {}
    tree = _Tree(source)
    live = _live_ids(source)
    sections: list[dict] = []

    head = _head_fields(tree, source, labels)
    if head:
        sections.append({'id': 'head', 'titulo': 'Aba do navegador e compartilhamento',
                         'ancora': None, 'campos': head})

    def new_section(node):
        title = _section_title(node, source)
        if node.tag == 'nav':
            title = 'Menu de navegação'
        elif node.tag == 'footer':
            title = 'Rodapé'
        elif node.tag == 'header' and not title:
            title = 'Topo'
        section = {'id': f's{len(sections)}', 'titulo': title or node.attrs.get('id') or node.tag,
                   'ancora': node.attrs.get('id'), 'campos': []}
        sections.append(section)
        return section

    loose = {'id': 'solto', 'titulo': 'Janelas e avisos fora das seções',
             'ancora': None, 'campos': []}

    def walk(node, section):
        for child in node.children:
            if child.tag in OPAQUE or child.tag in ('head', 'title', 'meta'):
                continue
            if child.tag in LANDMARKS and (child.attrs.get('id') or child.tag in ('nav', 'footer', 'header')):
                walk(child, new_section(child))
                continue
            is_field = child.tag not in VOID and _any_text(child) and _only_inline(child) \
                and (child.tag not in INLINE or not node.has_text)
            if child.attrs.get('id') in live:
                # A script writing into a text element owns its text. A container the
                # script only opens or scrolls to (a modal) still has editable copy.
                if not is_field:
                    walk(child, section)
                continue
            if is_field:
                target = section if section is not None else loose
                field = _field(child, source, live, labels,
                               f'{target["id"]}.f{len(target["campos"])}')
                if field:
                    target['campos'].append(field)
                continue
            walk(child, section)

    walk(tree.root, None)
    if loose['campos']:
        sections.append(loose)
    sections = [s for s in sections if s['campos']]

    # A token copied along with pasted HTML would point at two fields: neither keeps it.
    seen: dict[str, int] = {}
    for field in (f for s in sections for f in s['campos']):
        if field.get('token'):
            seen[field['token']] = seen.get(field['token'], 0) + 1
    for field in (f for s in sections for f in s['campos']):
        if field.get('token') and seen[field['token']] > 1:
            field['token'] = ''
    return sections


def _head_fields(tree: _Tree, source: str, labels: dict) -> list[dict]:
    fields = []

    def simple(field_id, label, span):
        raw = source[span[0]:span[1]]
        fields.append({'id': field_id, 'token': '', 'tipo': 'texto', 'tag': 'meta',
                       'rotulo': label, 'html': _markers_to_chips(raw, labels),
                       'texto': html.unescape(raw).strip(), 'estilo': '',
                       'hash': _digest(raw, ''), 'simples': True, '_raw': raw, '_span': span,
                       '_tag_span': None, '_locks': [], '_markers': MARKER.findall(raw)})

    def visit(node):
        for child in node.children:
            if child.tag == 'title':
                simple('head.title', 'Título da aba', (child.inner_start, child.inner_end))
            elif child.tag == 'meta':
                for (key, value), label in HEAD_META.items():
                    if child.attrs.get(key) == value:
                        span = _attr_span(source, child.start, child.inner_start, 'content')
                        if span:
                            simple(f'head.{value}', label, span)
            elif child.tag in ('html', 'head'):
                visit(child)

    visit(tree.root)
    return fields


def _attr_span(source: str, start: int, end: int, name: str):
    match = re.search(rf'\s{name}\s*=\s*(["\'])(.*?)\1', source[start:end], re.S)
    if not match:
        return None
    return start + match.start(2), start + match.end(2)


def public(sections: list[dict]) -> list[dict]:
    """Sections without the internal fields, for the panel."""
    return [{**s, 'campos': [{k: v for k, v in f.items() if not k.startswith('_')}
                             for f in s['campos']]} for s in sections]


def find_field(sections: list[dict], key: str) -> dict | None:
    """A field by its token (what the page carries) or by its position id."""
    for field in (f for s in sections for f in s['campos']):
        if key and (field.get('token') == key or field['id'] == key):
            return field
    return None


# ---------------------------------------------------------------- sanitizing
class _Sanitizer(HTMLParser):
    """Rebuilds a fragment keeping only inline markup and safe attributes.

    Chips turn back into what they stand for: data-marker="X" into @@X@@, and
    data-lock="N" into the N-th locked element, taken from the file, never from
    the request. Anything else not allowed is dropped, keeping its text.
    """

    def __init__(self, locks: list[str]):
        super().__init__(convert_charrefs=True)
        self.locks = locks
        self.out: list[str] = []
        self.open: list[str | None] = []
        self.skip = 0
        self.markers: list[str] = []
        self.used_locks: list[int] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.skip:
            if tag not in VOID:
                self.skip += 1
            return
        if attrs.get('data-marker') is None and attrs.get('data-lock') is None and tag in OPAQUE:
            self.skip += 1
            return
        if attrs.get('data-marker') is not None:
            name = attrs['data-marker'] or ''
            if re.fullmatch(r'[A-Z_]+', name):
                self.out.append(f'@@{name}@@')
                self.markers.append(name)
            if tag not in VOID:
                self.skip += 1
            return
        if attrs.get('data-lock') is not None:
            number = attrs['data-lock'] or ''
            # A second copy of the same live element is dropped: its id must stay unique.
            if number.isdigit() and int(number) < len(self.locks) and int(number) not in self.used_locks:
                self.out.append(self.locks[int(number)])
                self.used_locks.append(int(number))
            if tag not in VOID:
                self.skip += 1
            return
        if tag == 'br':
            self.out.append('<br>')
            return
        if tag in ('div', 'p') and self.out:
            # A browser turns Enter into a new block; inside a field that is a line break.
            self.out.append('<br>')
        if tag == 'font':
            # execCommand still emits <font> for some commands; keep it as a styled span.
            css = []
            if attrs.get('face'):
                css.append(f"font-family: {attrs['face']}")
            if attrs.get('color'):
                css.append(f"color: {attrs['color']}")
            tag, attrs = 'span', {'style': '; '.join(css + [attrs.get('style') or ''])}
        if tag not in INLINE:
            if tag not in VOID:
                self.open.append(None)
            return
        kept = []
        for name, value in attrs.items():
            if value is None or name not in ALLOWED_ATTRS.get(tag, set()) | COMMON_ATTRS:
                continue
            if name == 'href' and not SAFE_URL.match(value.strip()):
                continue
            if name == 'style':
                value = clean_css(value)
                if not value:
                    continue
            if name == 'data-vivo' and not LIVE_KEY.match(value):
                continue
            if name == 'class':
                # The editor's own marks (jarl-chip, jarl-active...) never reach the page.
                value = ' '.join(c for c in value.split() if not c.startswith('jarl-'))
                if not value:
                    continue
            kept.append(f' {name}="{html.escape(value, quote=True)}"')
        # A bare <span> stays: pages style it by position (the home menu hides its
        # labels in one until hover), so dropping it would change how the page looks.
        self.out.append(f'<{tag}{"".join(kept)}>')
        self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag == 'br' and not self.skip:
            self.out.append('<br>')

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.skip:
            self.skip -= 1
            return
        if self.open:
            kept = self.open.pop()
            if kept:
                self.out.append(f'</{kept}>')

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.open:
            kept = self.open.pop()
            if kept:
                self.out.append(f'</{kept}>')
        text = ''.join(self.out).replace(' ', '&nbsp;').strip()
        return re.sub(r'(<br>\s*)+$', '', text)


def sanitize(fragment: str, locks: list[str] | None = None, simple: bool = False):
    """Clean HTML, plus the markers and locks it carried."""
    parser = _Sanitizer(locks or [])
    parser.feed(fragment)
    parser.close()
    result = parser.result()
    if simple:
        # Plain text (title, meta, mod description): no tags at all.
        text = re.sub(r'<br>', ' ', result)
        result = html.escape(_plain(text), quote=True)
    return result, parser.markers, parser.used_locks


def _same(a: str, b: str) -> bool:
    squash = lambda s: re.sub(r'\s+', ' ', html.unescape(s)).strip()
    return squash(a) == squash(b)


def _check(field: dict, new: str, markers: list, locks: list, known: set):
    """Live elements must come back exactly once: the page's scripts write into
    them. Build markers may be removed from a field (the page-wide check in apply
    keeps each one somewhere), but never invented."""
    name = field.get('rotulo') or field['texto'][:40]
    # A live value that left the text (retyped, or unwrapped by a format command) is
    # an edit like any other: the page's scripts check the element exists first.
    if set(markers) - known:
        raise TextError(f'"{name}": valor automático desconhecido nesta página')
    if not HAS_WORD.search(_plain(new)) and not markers:
        raise TextError(f'"{name}" ficou vazio')


# ---------------------------------------------------------------- blocks
BLOCK_ATTR = 'data-bloco'
TOP = {'#root', 'html', 'body', 'main', 'head'}
ID_FORM = re.compile(r'^[a-z][a-z0-9-]{0,40}$')


def _ancestors(node: _Node):
    """The node's parents that can be selected as blocks: up to, not past, the page body."""
    parent = node.parent
    while parent is not None and parent.tag not in TOP:
        yield parent
        parent = parent.parent


def _subtree(node: _Node):
    yield node
    for child in node.children:
        yield from _subtree(child)


LIVE_REASON = 'tem valores que o script antigo da página atualiza pelo nome (id)'


def _protection(node: _Node, source: str, live: set, available: set, force: bool = False) -> str:
    """Why a block may not be removed or duplicated, or '' if it may.

    Unknown generated markers are kept protected. Elements an old page script
    updates by id may, when forced: the
    editor asks first, and the only loss is that copy not updating.
    """
    if set(MARKER.findall(source[node.start:node.end])) - available:
        return 'tem um valor automático que esta página não conhece'
    if not force and any(n.attrs.get('id') in live for n in _subtree(node)):
        return LIVE_REASON
    return ''


def blocks(source: str, available: set | None = None) -> dict:
    """Every selectable container of an editable field, by token.

    Only stamped blocks are listed: the in-page editor finds them by their
    data-bloco attribute, so they can be picked even where the browser's DOM
    differs from the file (a table gains a <tbody> in the browser, not here).
    """
    available = set(available or ())
    tree = _Tree(source)
    live = _live_ids(source)
    found = {}
    for field in (f for s in extract(source) for f in s['campos'] if f.get('_node')):
        for node in _ancestors(field['_node']):
            token = node.attrs.get(BLOCK_ATTR) or ''
            if not TOKEN.match(token) or token in found:
                continue
            reason = _protection(node, source, live, available)
            inner_ids = [n.attrs['id'] for n in _subtree(node) if n is not node and n.attrs.get('id')]
            found[token] = {'tag': node.tag, 'protegido': reason,
                            'forcavel': reason == LIVE_REASON,
                            'duplicavel': not reason and not inner_ids,
                            'secao': node.tag in LANDMARKS}
    return found


def _find(tree: _Tree, token: str) -> _Node:
    if not TOKEN.match(token or ''):
        raise TextError('bloco inválido')
    hits = [n for n in _subtree(tree.root)
            if n.attrs.get(BLOCK_ATTR) == token or n.attrs.get(TOKEN_ATTR) == token]
    if len(hits) != 1:
        raise TextError('esse bloco não existe mais nesta página; recarregue')
    node = hits[0]
    if node.tag in TOP or any(a.tag == 'head' for a in _ancestors(node)):
        raise TextError('esse bloco não pode ser mexido')
    return node


def _line_span(source: str, node: _Node) -> tuple[int, int, str]:
    """The node's span widened to whole lines when it sits alone on its lines."""
    line_start = source.rfind('\n', 0, node.start) + 1
    indent = source[line_start:node.start]
    end = node.end
    if indent.strip() == '' and source[end:end + 1] == '\n':
        return line_start, end + 1, indent
    return node.start, node.end, ''


def _indented(fragment: str, indent: str) -> str:
    return fragment.replace('\n', '\n' + indent)


def _new_tokens(mapping: dict, source: str) -> dict:
    """Tokens the editor made up for new blocks: well formed and not in use."""
    clean = {}
    for key, value in (mapping or {}).items():
        value = str(value)
        if key == 'vivo':
            if not LIVE_KEY.match(value):
                raise TextError('dado ao vivo inválido')
            clean[key] = value
            continue
        if key == '#id' or key == 'id':
            if not ID_FORM.match(value) or re.search(rf'\sid="{re.escape(value)}"', source):
                raise TextError(f'âncora inválida ou repetida: {value}')
        elif not TOKEN.match(value) or f'"{value}"' in source:
            raise TextError('marca de bloco repetida; recarregue a página')
        clean[str(key)] = value
    unique = [v for k, v in clean.items() if k != 'vivo']
    if len(set(unique)) != len(unique):
        raise TextError('marca de bloco repetida no pedido')
    return clean


def _apply_op(source: str, op: dict, models: dict, live: set, available: set) -> tuple[str, set]:
    """One structural operation on the source. Returns the new source and the
    tokens it created (fields there have no digest to check yet)."""
    kind = op.get('op')
    tree = _Tree(source)
    node = _find(tree, str(op.get('alvo') or ''))

    force = bool(op.get('forcar'))
    if kind == 'remover':
        reason = _protection(node, source, live, available, force)
        if reason:
            raise TextError(f'esse bloco não pode ser removido: {reason}')
        start, end, _ = _line_span(source, node)
        return source[:start] + source[end:], set()

    if kind == 'mover':
        siblings = [c for c in node.parent.children if c.tag not in OPAQUE or c is node]
        index = siblings.index(node)
        other_index = index - 1 if op.get('direcao') == 'cima' else index + 1
        if not 0 <= other_index < len(siblings):
            raise TextError('esse bloco já está no limite')
        first, second = sorted((node, siblings[other_index]), key=lambda n: n.start)
        a, b = source[first.start:first.end], source[second.start:second.end]
        return (source[:first.start] + b + source[first.end:second.start] + a
                + source[second.end:]), set()

    if kind == 'duplicar':
        reason = _protection(node, source, live, available, force)
        if reason:
            raise TextError(f'esse bloco não pode ser duplicado: {reason}')
        tokens = _new_tokens(op.get('tokens'), source)
        copy = source[node.start:node.end]
        if force:
            # Names must stay unique: the copy's inner elements lose theirs (they
            # stop being updated by the old script, which is what was agreed to).
            for inner in _subtree(node):
                inner_id = inner.attrs.get('id')
                if inner is not node and inner_id:
                    copy = re.sub(rf'\sid="{re.escape(inner_id)}"', '', copy, count=1)
        for old in set(re.findall(rf'(?:{TOKEN_ATTR}|{BLOCK_ATTR})="([a-z0-9]+)"', copy)):
            if old not in tokens:
                raise TextError('faltou marca nova para uma parte do bloco duplicado')
            copy = copy.replace(f'"{old}"', f'"{tokens[old]}"')
        ids = [n.attrs['id'] for n in _subtree(node) if n.attrs.get('id')]
        if force:
            ids = [i for i in ids if i == node.attrs.get('id')]
        if ids and (ids != [node.attrs.get('id')] or '#id' not in tokens):
            raise TextError('esse bloco tem elementos com nome próprio e não pode ser duplicado')
        if ids:
            copy = copy.replace(f'id="{ids[0]}"', f'id="{tokens["#id"]}"', 1)
        _, end, indent = _line_span(source, node)
        if end == node.end + 1:            # alone on its lines: the copy goes on the next ones
            where, insert = end, indent + copy + '\n'
        else:                              # inline among others (a button in a row)
            where, insert = node.end, ' ' + copy
        return source[:where] + insert + source[where:], set(tokens.values())

    if kind == 'inserir':
        model = models.get(str(op.get('modelo')))
        if not model:
            raise TextError('modelo de bloco desconhecido')
        if model.get('secao') and node.tag not in LANDMARKS:
            raise TextError('seção nova entra antes ou depois de outra seção')
        tokens = _new_tokens(op.get('tokens'), source)
        fragment = model['html']
        for key in set(re.findall(r'\{([a-z0-9#]+)\}', fragment)):
            value = tokens.get('#id' if key == 'id' else key)
            if value is None:
                raise TextError('faltou marca para o bloco novo')
            fragment = fragment.replace('{' + key + '}', value)
        start, end, indent = _line_span(source, node)
        whole_lines = end == node.end + 1
        if op.get('posicao') == 'antes':
            where = start if whole_lines else node.start
            text = indent + _indented(fragment, indent) + '\n' if whole_lines else fragment + ' '
        else:
            where = end if whole_lines else node.end
            text = indent + _indented(fragment, indent) + '\n' if whole_lines else ' ' + fragment
        if model.get('secao'):
            text = ('\n' + text) if op.get('posicao') != 'antes' else (text + '\n')
        return source[:where] + text + source[where:], set(tokens.values())

    if kind == 'estilo':
        tag_text = source[node.start:node.inner_start]
        new_tag = _set_attr(tag_text, 'style', clean_css(str(op.get('estilo') or '')) or None)
        return source[:node.start] + new_tag + source[node.inner_start:], set()

    if kind == 'link':
        if node.tag != 'a':
            raise TextError('esse bloco não é um link')
        href = str(op.get('href') or '').strip()
        if not SAFE_URL.match(href):
            raise TextError('endereço de link inválido (use https://, / ou #)')
        tag_text = _set_attr(source[node.start:node.inner_start], 'href', href)
        new_tab = bool(op.get('nova_aba'))
        tag_text = _set_attr(tag_text, 'target', '_blank' if new_tab else None)
        tag_text = _set_attr(tag_text, 'rel', 'noopener' if new_tab else None)
        return source[:node.start] + tag_text + source[node.inner_start:], set()

    raise TextError(f'operação desconhecida: {kind}')


def stamp(source: str) -> str:
    """Gives every field and every block a unique token; the first of a repeated
    token keeps it, later copies get new ones."""
    tree = _Tree(source)
    wanted = set()
    for field in (f for s in extract(source) for f in s['campos'] if f.get('_node')):
        wanted.add((field['_node'], TOKEN_ATTR))
        for node in _ancestors(field['_node']):
            wanted.add((node, BLOCK_ATTR))
    seen = set(re.findall(rf'(?:{TOKEN_ATTR}|{BLOCK_ATTR})="([a-z0-9]+)"', source))
    used = set()
    edits = []
    for node in sorted({n for n, _ in wanted}, key=lambda n: n.start):
        tag_text = source[node.start:node.inner_start]
        new_tag = tag_text
        for attr in (TOKEN_ATTR, BLOCK_ATTR):
            if (node, attr) not in wanted:
                continue
            token = node.attrs.get(attr) or ''
            if TOKEN.match(token) and token not in used:
                used.add(token)
                continue
            fresh = secrets.token_hex(4)
            while fresh in seen or fresh in used:
                fresh = secrets.token_hex(4)
            used.add(fresh)
            new_tag = _set_attr(new_tag, attr, fresh)
        if new_tag != tag_text:
            edits.append((node.start, node.inner_start, new_tag))
    for start, end, new_tag in reversed(edits):
        source = source[:start] + new_tag + source[end:]
    return source


BLOCK_NAMES = {'section': 'a seção', 'header': 'o topo', 'footer': 'o rodapé', 'nav': 'o menu',
               'ul': 'a lista', 'ol': 'a lista', 'li': 'o item', 'table': 'a tabela',
               'tr': 'a linha', 'td': 'a célula', 'th': 'o cabeçalho', 'p': 'o parágrafo',
               'a': 'o link', 'h1': 'o título', 'h2': 'o título', 'h3': 'o título',
               'h4': 'o subtítulo', 'span': 'o trecho', 'div': 'o bloco'}


def describe(source: str, token: str) -> str:
    """A block in words, for the version list: 'a caixa «O que você precisa saber»'."""
    tree = _Tree(source)
    hits = [n for n in _subtree(tree.root)
            if token and (n.attrs.get(BLOCK_ATTR) == token or n.attrs.get(TOKEN_ATTR) == token)]
    if not hits:
        return 'um bloco'
    node = hits[0]
    cls = node.attrs.get('class', '')
    name = ('a caixa' if 'caixa' in cls else 'o quadro' if 'celula' in cls
            else 'o cartão' if 'cartao' in cls else BLOCK_NAMES.get(node.tag, 'o bloco'))
    text = (_section_title(node, source) if node.tag in LANDMARKS else None) or \
        _plain(MARKER.sub('', source[node.inner_start:node.inner_end]))
    text = text[:45] + ('…' if len(text) > 45 else '')
    return f'{name} «{text}»' if text else name


# ---------------------------------------------------------------- saving
def apply(source: str, changes: list[dict], labels: dict | None = None,
          available: set | None = None, ops: list | None = None,
          models: dict | None = None) -> tuple[str, int]:
    """New file text with the changes applied, and how many things changed.

    First the structural operations, in the order they were made (remove, move,
    duplicate, insert, block style, block link); then the field edits, each
    {'campo': token, 'hash': digest the editor read, 'html': ..., 'estilo': ...}.
    Fields created by this batch carry no digest. Last, every field and block
    still without a token gets one, so the published page can be edited in place.
    """
    available = set(available or ())
    structural = set(MARKER.findall(source)) - available
    known = structural | available
    live = _live_ids(source)
    created: set = set()
    changed = 0
    for op in ops or []:
        source, new_tokens = _apply_op(source, op, models or {}, live, available)
        created |= new_tokens
        changed += 1

    sections = extract(source, labels)
    edits = []
    touched = set()
    for change in changes:
        key = str(change.get('campo') or '')
        field = find_field(sections, key)
        if field is None:
            raise TextError('esse trecho não existe mais nesta página; recarregue')
        if key not in created and field['hash'] != change.get('hash'):
            raise TextError('esse trecho mudou desde que você abriu; recarregue antes de gravar')
        if field['id'] in touched:
            raise TextError('o mesmo trecho veio duas vezes')
        touched.add(field['id'])
        new_inner = None
        if 'html' in change:
            new, markers, locks = sanitize(str(change['html']), field['_locks'],
                                           simple=bool(field.get('simples')))
            _check(field, new, markers, locks, known)
            if not _same(new, field['_raw']):
                new_inner = new
        new_tag = None
        if field['_tag_span']:
            start, end = field['_tag_span']
            tag_text = source[start:end]
            if 'estilo' in change:
                style = clean_css(str(change['estilo'] or ''))
                if style != clean_css(field['estilo']):
                    tag_text = _set_attr(tag_text, 'style', style or None)
            if tag_text != source[start:end]:
                new_tag = (start, end, tag_text)
        if new_inner is None and new_tag is None:
            continue
        changed += 1
        if new_inner is not None:
            edits.append((*field['_span'], new_inner))
        if new_tag is not None:
            edits.append(new_tag)

    for start, end, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        source = source[:start] + replacement + source[end:]
    # Value tags are optional; a structural marker (the mod list, the embers) is
    # what the generator needs, and losing its last copy would stop the build.
    gone = structural - set(MARKER.findall(source))
    if gone:
        names = ', '.join(sorted((labels or {}).get(m, m) for m in gone))
        raise TextError(f'o valor automático "{names}" precisa continuar em pelo menos um lugar '
                        'da página; esta alteração tiraria o último')
    return stamp(source), changed


# ---------------------------------------------------------------- manifest
def load_manifest(site_dir: Path) -> dict:
    try:
        manifest = json.loads((site_dir / MANIFEST).read_text(encoding='utf-8'))
        pages = manifest['paginas']
    except (OSError, json.JSONDecodeError, KeyError) as error:
        raise TextError(f'não consegui ler {MANIFEST} do site: {error}') from error
    root = site_dir.resolve()
    for page in pages:
        if not re.fullmatch(r'[a-z0-9-]{1,40}', page.get('id', '')):
            raise TextError(f'id de página inválido em {MANIFEST}: {page.get("id")!r}')
        paths = [page.get('fonte'), page.get('saida'), *(page.get('arquivos') or [])]
        for relative in filter(None, paths):
            resolved = (site_dir / relative).resolve()
            if root not in resolved.parents:
                raise TextError(f'a página {page["id"]} aponta para fora da pasta do site')
    return manifest


def marker_labels(manifest: dict) -> dict:
    return {name: (spec.get('rotulo') if isinstance(spec, dict) else spec) or name
            for name, spec in (manifest.get('marcadores') or {}).items()}


def available_markers(manifest: dict, page: dict) -> set:
    """Tags this page's generator fills in, so the editor may insert them."""
    return set(manifest.get('marcadores') or {}) if page.get('valores') else set()


def find_page(site_dir: Path, page_id: str) -> tuple[dict, dict]:
    manifest = load_manifest(site_dir)
    for page in manifest['paginas']:
        if page['id'] == page_id:
            return manifest, page
    raise TextError(f'não conheço a página {page_id!r}')


def page_for_url(site_dir: Path, url_path: str) -> tuple[dict, dict]:
    """The page published at this address (/, /wiki/ ...)."""
    manifest = load_manifest(site_dir)
    wanted = '/' + url_path.strip('/') + '/' if url_path.strip('/') else '/'
    for page in manifest['paginas']:
        if page.get('url') == wanted:
            return manifest, page
    raise TextError('esta página do site ainda não é editável')


# ---------------------------------------------------------------- mod list
def mod_fields(site_dir: Path, page: dict) -> list[dict]:
    """The mod list on the home page is built from a JSON of descriptions."""
    spec = page.get('mods')
    if not spec:
        return []
    listing = json.loads((site_dir / spec['lista']).read_text(encoding='utf-8'))
    fields = []
    for mod in listing['mods']:
        text = mod['descricao']
        fields.append({'id': f'mod.{mod["pacote"]}', 'token': f'mod.{mod["pacote"]}',
                       'tipo': 'texto', 'tag': 'mod', 'rotulo': f'{mod["nome"]} · {mod["autor"]}',
                       'html': html.escape(text), 'texto': text, 'estilo': '',
                       'hash': _digest(text, ''), 'simples': True,
                       'original': mod.get('original', ''), 'versao': mod.get('versao', '')})
    return [{'id': 'mods', 'titulo': f'Descrições dos mods ({len(fields)})',
             'ancora': spec.get('ancora'), 'campos': fields}]


def apply_mods(site_dir: Path, page: dict, changes: list[dict]) -> tuple[int, dict]:
    """New contents for the description file and the built list, keyed by path."""
    spec = page['mods']
    listing_path = site_dir / spec['lista']
    texts_path = site_dir / spec['descricoes']
    listing = json.loads(listing_path.read_text(encoding='utf-8'))
    texts = json.loads(texts_path.read_text(encoding='utf-8'))
    by_package = {m['pacote']: m for m in listing['mods']}
    changed = 0
    for change in changes:
        package = str(change.get('campo', ''))[len('mod.'):]
        mod = by_package.get(package)
        if mod is None:
            raise TextError(f'o mod {package} não está mais na lista')
        if _digest(mod['descricao'], '') != change.get('hash'):
            raise TextError('a lista de mods mudou desde que você abriu; recarregue antes de gravar')
        new = html.unescape(sanitize(str(change.get('html', '')), simple=True)[0])
        if MARKER.search(new):
            raise TextError('a descrição de mod não aceita valores automáticos')
        if not HAS_WORD.search(new):
            raise TextError(f'a descrição de {mod["nome"]} ficou vazia')
        if new == mod['descricao']:
            continue
        mod['descricao'] = new
        mod['traduzida'] = True
        texts[package] = new
        changed += 1
    if not changed:
        return 0, {}
    return changed, {
        listing_path: json.dumps(listing, ensure_ascii=False, indent=1),
        texts_path: json.dumps(texts, ensure_ascii=False, indent=2) + '\n',
    }
