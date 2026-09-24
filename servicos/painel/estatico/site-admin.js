/* In-page editor for the public site.
 *
 * Loaded only when the "jarl" hint cookie exists (see the loader snippet in the
 * site's pages), and it does nothing until the panel confirms a real session.
 *
 * Two kinds of edits, one history:
 *   - text and style of a field (a paragraph, a heading, a button label);
 *   - structure: remove, move, duplicate or add a block, restyle a whole block,
 *     change where a link points.
 * Everything is a draft until "Salvar"; Ctrl+Z and Ctrl+Shift+Z walk the same
 * history for both kinds. Saving sends the structural operations in the order
 * they were made, then the final text of every changed field; the panel applies
 * them to the page source, rebuilds and publishes.
 *
 * Blocks are found by the data-bloco / data-campo tokens the source carries,
 * never by position, so the browser's own DOM quirks (a <tbody> the file does
 * not have) cannot make an operation hit the wrong element.
 */
(() => {
  if (window.__jarlEditor) return;
  window.__jarlEditor = true;

  const ROOT = '/jarl';
  const EDITING_KEY = 'jarl-editando';
  const HINT = 'jarl';
  // Inside the full-screen editor (/jarl/editor) the page runs in a frame and the
  // tools live in the editor's left sidebar: same origin, so this script builds
  // them straight into the parent document.
  const SHELL = (() => { try { return window.parent !== window && window.parent.jarlShell || null; }
                         catch { return null; } })();
  const H = SHELL ? window.parent.document : document;
  const LANDMARKS = new Set(['SECTION', 'HEADER', 'FOOTER', 'NAV', 'ASIDE']);
  const OPAQUE = new Set(['SCRIPT', 'STYLE', 'SVG', 'NOSCRIPT', 'TEMPLATE', 'TEXTAREA', 'SELECT',
                          'CANVAS', 'IFRAME', 'OBJECT', 'VIDEO', 'AUDIO', 'PICTURE', 'MATH']);
  // Properties a site stylesheet often sets on <strong>, <a>...: painting a field
  // also makes its inner pieces follow, or the old color would win inside it.
  const INHERITED = new Set(['color', 'font-family']);

  const FONTS = [
    ['Padrão do site', ''],
    ['Cinzel (títulos)', "'Cinzel', serif"],
    ['Spectral (texto)', "'Spectral', Georgia, serif"],
    ['Georgia', 'Georgia, serif'],
    ['Sem serifa', 'system-ui, sans-serif'],
    ['Monoespaçada', 'ui-monospace, Menlo, monospace'],
  ];
  const SIZES = [
    ['Pequeno', '0.85em'], ['Normal', ''], ['Médio', '1.15em'],
    ['Grande', '1.35em'], ['Enorme', '1.7em'], ['Gigante', '2.2em'],
  ];
  const COLORS = [
    ['Ouro', '#c8a45c'], ['Ouro claro', '#eeddb0'], ['Brasa', '#ff8b3d'],
    ['Brasa clara', '#ffc477'], ['Osso', '#e6e0d2'], ['Texto', '#b4bec7'],
    ['Apagado', '#78848f'], ['Branco', '#ffffff'], ['Sangue', '#c0392b'],
    ['Musgo', '#7fae6a'], ['Gelo', '#8ec5e8'],
  ];
  const BORDERS = [
    ['Nenhuma', null],
    ['Fina dourada', {border: '1px solid #c8a45c', padding: '0.35em 0.6em', 'border-radius': '6px'}],
    ['Grossa dourada', {border: '2px solid #c8a45c', padding: '0.45em 0.75em', 'border-radius': '8px'}],
    ['Brasa', {border: '1px solid #ff8b3d', padding: '0.35em 0.6em', 'border-radius': '6px'}],
    ['Sangue', {border: '1px solid #c0392b', padding: '0.35em 0.6em', 'border-radius': '6px'}],
    ['Tracejada', {border: '1px dashed #78848f', padding: '0.35em 0.6em', 'border-radius': '6px'}],
    ['Pílula', {border: '1px solid #c8a45c', padding: '0.25em 0.9em', 'border-radius': '999px'}],
    ['Caixa com sombra', {border: '1px solid #33475a', padding: '0.5em 0.8em', 'border-radius': '8px',
                          'box-shadow': '0 6px 18px rgba(0,0,0,0.55)'}],
  ];
  const SHADOWS = [
    ['Nenhuma', ''],
    ['Suave', '0 1px 3px rgba(0,0,0,0.85)'],
    ['Relevo', '1px 1px 0 #000'],
    ['Brilho dourado', '0 0 10px rgba(200,164,92,0.85)'],
    ['Brilho de brasa', '0 0 12px rgba(255,139,61,0.9)'],
    ['Brilho de sangue', '0 0 10px rgba(192,57,43,0.9)'],
    ['Aura de gelo', '0 0 10px rgba(142,197,232,0.85)'],
  ];
  const BOX_KEYS = ['border', 'padding', 'border-radius', 'box-shadow'];

  // ------------------------------------------------------------ state
  const S = {
    user: null,
    editing: false,
    page: null,          // {id, titulo, url, somente_leitura}
    fields: new Map(),   // token -> field from the panel (or made here for new blocks)
    elements: new Map(), // token -> element on this page
    base: new Map(),     // token -> {html, style} as first shown in the editor form
    original: new Map(), // token -> {html, style} as published, to restore when untouched
    swapped: new Set(),  // tokens whose element holds the editor form
    created: new Set(),  // field tokens born in this session (duplicated or added)
    blocks: {},          // block token -> {protegido, duplicavel, secao}
    models: [],          // [{chave, rotulo, secao, html}] this page's templates for new blocks
    destinations: [],    // [{rotulo, href}] quick targets for links
    values: [],          // tags this page may carry: [{chave, rotulo, descricao, uso, valor}]
    titles: {},          // section anchor -> title, for the breadcrumb
    active: null,        // token of the field being edited
    block: null,         // element selected in the breadcrumb (the field itself or a parent)
    past: [],            // [{kind: 'campo', token, before, after} | {kind: 'op', op, undo, redo}]
    future: [],
    typing: null,        // {token, before, timer} while a burst of typing is open
    stable: null,        // snapshot of the active field before the next keystroke
    applying: false,     // a toolbar command is changing the DOM right now
    savedRange: null,
    busy: false,
    newSections: new Set(),  // sections born in this session (offered for the menu)
    menuLinks: new Map(),    // section -> menu entry created for it
  };
  const tokenOf = new WeakMap();

  // ------------------------------------------------------------ helpers
  const $ = (tag, attrs = {}, ...kids) => {
    const el = H.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'on') for (const [e, f] of Object.entries(v)) el.addEventListener(e, f);
      else if (k === 'class') el.className = v;
      else if (v !== undefined && v !== null && v !== false) el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid);
    return el;
  };
  const squash = s => (s || '').replace(/\s+/g, ' ').trim();
  const newToken = () => {
    let t;
    do { t = Math.random().toString(16).slice(2, 10).padEnd(8, '0'); }
    while (document.querySelector(`[data-campo="${t}"],[data-bloco="${t}"]`));
    return t;
  };
  const blockToken = el => el.dataset.campo || el.dataset.bloco || '';
  const isField = el => !!el && tokenOf.has(el);

  async function api(path, body) {
    const opts = {credentials: 'same-origin', headers: {}};
    if (body !== undefined) {
      opts.method = 'POST';
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(ROOT + path, opts);
    if (r.status === 401) throw Object.assign(new Error('sessão expirada'), {expired: true});
    const d = await r.json().catch(() => ({ok: false, erro: 'resposta ilegível do painel'}));
    if (!d.ok) throw new Error(d.erro || 'não deu');
    return d;
  }

  function note(text) {
    if (!ui.note) { if (text) toast(text, 'erro'); return; }
    ui.note.textContent = text || '';
    ui.note.hidden = !text;
  }

  function toast(text, kind = 'ok', action) {
    const box = $('div', {class: `jarl-toast jarl-${kind}`}, text);
    if (action) {
      box.classList.add('jarl-toast-acao');
      box.append($('button', {class: 'jarl-btn jarl-small', on: {click: () => { box.remove(); action.run(); }}},
                   action.label));
    }
    ui.toasts.append(box);
    setTimeout(() => box.remove(), action ? 15000 : kind === 'erro' ? 9000 : 5000);
  }

  function parseStyle(text) {
    const map = new Map();
    for (const part of (text || '').split(';')) {
      const i = part.indexOf(':');
      if (i > 0) map.set(part.slice(0, i).trim().toLowerCase(), part.slice(i + 1).trim());
    }
    return map;
  }
  const styleText = map => [...map].filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`).join('; ');
  function writeStyle(el, text) {
    if (text) el.setAttribute('style', text); else el.removeAttribute('style');
  }

  // ------------------------------------------------------------ ui
  const ui = {};
  function buildUi() {
    document.head.append($('link', {rel: 'stylesheet', href: `${ROOT}/estatico/site-admin.css`}));
    if (SHELL) {
      // No dock and no ribbon on the page: the sidebar has both.
      ui.toasts = SHELL.toasts;
      ui.toolbar = SHELL.toolbarHost;
      ui.menu = $('div', {class: 'jarl-menu', 'data-jarl-ui': '', hidden: true});
      document.body.append(ui.menu);
      return;
    }
    ui.count = $('span', {class: 'jarl-count'}, '0');
    ui.undo = $('button', {class: 'jarl-btn', title: 'Desfazer (Ctrl+Z)', on: {click: undo}}, '↶');
    ui.redo = $('button', {class: 'jarl-btn', title: 'Refazer (Ctrl+Shift+Z)', on: {click: redo}}, '↷');
    ui.discard = $('button', {class: 'jarl-btn', on: {click: discardAll}}, 'Descartar');
    ui.save = $('button', {class: 'jarl-btn jarl-primary', title: 'Salvar (Ctrl+S)', on: {click: save}},
                'Salvar ', ui.count);
    ui.toggle = $('button', {class: 'jarl-btn jarl-toggle', on: {click: () => setEditing(!S.editing)}},
                  'Modo edição');
    ui.preview = $('button', {class: 'jarl-btn', title: 'Link para mostrar as alterações antes de publicar',
                              on: {click: makePreview}}, 'Prévia');
    ui.editBar = $('div', {class: 'jarl-editbar'}, ui.undo, ui.redo, ui.preview, ui.discard, ui.save);
    ui.note = $('div', {class: 'jarl-note', hidden: true});
    ui.dock = $('div', {class: 'jarl-dock', 'data-jarl-ui': ''},
      $('a', {class: 'jarl-brand', href: `${ROOT}/`, target: '_top', title: 'Painel do servidor'},
        $('span', {class: 'jarl-rune'}, 'ᛃ'), 'Jarl'),
      $('a', {class: 'jarl-btn', href: `${ROOT}/editor?url=${encodeURIComponent(location.pathname)}`, target: '_top',
              title: 'Editor em tela cheia, com elementos e dados ao vivo para arrastar'}, 'Tela cheia'),
      ui.toggle, ui.editBar, ui.note);
    ui.toasts = $('div', {class: 'jarl-toasts', 'data-jarl-ui': ''});
    ui.toolbar = $('div', {class: 'jarl-toolbar', 'data-jarl-ui': '', hidden: true});
    ui.toolbar.addEventListener('mousedown', e => {
      // Keep the text selection in the page while clicking the toolbar.
      if (e.target.tagName !== 'INPUT') e.preventDefault();
    });
    ui.menu = $('div', {class: 'jarl-menu', 'data-jarl-ui': '', hidden: true});
    document.body.append(ui.dock, ui.toasts, ui.toolbar, ui.menu);
    refreshDock();
  }

  function refreshDock() {
    if (SHELL) {
      for (const [token, el] of S.elements) {
        const changed = fieldChanged(token);
        el.classList.toggle('jarl-changed', changed);
        el.classList.toggle('jarl-vazio', changed && isEmpty(token) && S.fields.get(token).tag !== 'mod');
      }
      SHELL.update(state());
      return;
    }
    if (!ui.dock) return;
    ui.dock.classList.toggle('jarl-on', S.editing);
    ui.toggle.textContent = S.editing ? 'Sair da edição' : 'Modo edição';
    ui.editBar.hidden = !S.editing;
    const n = pendingCount();
    ui.count.textContent = n;
    ui.save.disabled = !n || S.busy;
    ui.discard.disabled = !n || S.busy;
    ui.undo.disabled = !S.past.length && !S.typing;
    ui.redo.disabled = !S.future.length;
    for (const [token, el] of S.elements) {
      const changed = fieldChanged(token);
      el.classList.toggle('jarl-changed', changed);
      el.classList.toggle('jarl-vazio', changed && isEmpty(token) && S.fields.get(token).tag !== 'mod');
    }
  }

  // ------------------------------------------------------------ blocks and breadcrumb
  function blockLabel(el) {
    const tag = el.tagName;
    if (isField(el) && (tag === 'DIV' || tag === 'SPAN')) return 'Texto';
    if (LANDMARKS.has(tag)) {
      if (tag === 'NAV') return 'Menu';
      if (tag === 'FOOTER') return 'Rodapé';
      const title = S.titles[el.id] || (el.querySelector('h1,h2,h3') || {}).textContent;
      return 'Seção' + (title ? `: ${squash(title).slice(0, 28)}` : '');
    }
    const cls = el.classList;
    if (cls.contains('caixa')) return cls.contains('alerta') ? 'Caixa de alerta' : 'Caixa';
    if (cls.contains('cartao')) return 'Cartão';
    if (cls.contains('cartoes')) return 'Cartões';
    if (cls.contains('celula')) return 'Quadro';
    if (cls.contains('grade')) return 'Grade de quadros';
    if (cls.contains('painel')) return 'Painel';
    if (cls.contains('pg-item')) return 'Item do topo';
    const names = {UL: 'Lista', OL: 'Lista numerada', LI: 'Item', TABLE: 'Tabela', TR: 'Linha',
                   TD: 'Célula', TH: 'Cabeçalho', P: 'Parágrafo', A: 'Link', BUTTON: 'Botão',
                   H1: 'Título', H2: 'Título', H3: 'Título', H4: 'Subtítulo', H5: 'Subtítulo',
                   H6: 'Subtítulo', BLOCKQUOTE: 'Citação', SPAN: 'Trecho', DIV: 'Bloco'};
    if (tag === 'A' && cls.contains('botao')) return 'Botão';
    return names[tag] || tag.toLowerCase();
  }

  function crumbs() {
    const field = S.active && S.elements.get(S.active);
    if (!field) return [];
    const list = [field];
    for (let el = field.parentElement; el && el !== document.body && el.tagName !== 'MAIN';
         el = el.parentElement) {
      if (el.dataset.bloco) list.push(el);
    }
    return list;
  }

  function blockInfo(el) {
    if (isField(el)) {
      const field = S.fields.get(tokenOf.get(el));
      const live = (field.travas || []).some(Boolean);
      return {protegido: live ? 'tem valores que o script antigo da página atualiza pelo nome (id)' : '',
              forcavel: live, duplicavel: !live && !el.id && field.tag !== 'mod', mod: field.tag === 'mod'};
    }
    return S.blocks[el.dataset.bloco] ||
      {protegido: 'bloco sem marca nesta página; recarregue', duplicavel: false};
  }

  function selectBlock(el) {
    if (S.block) S.block.classList.remove('jarl-sel');
    S.block = el;
    if (el && !isField(el)) el.classList.add('jarl-sel');
    fillToolbar();
  }

  const target = () => S.block || (S.active && S.elements.get(S.active));
  const targetIsField = () => { const t = target(); return !!t && tokenOf.get(t) === S.active; };

  // ------------------------------------------------------------ toolbar and menus
  function formatActions() {
    const field = S.active && S.fields.get(S.active);
    if (!field || (field.simples && targetIsField())) return [];
    const blockLevel = !targetIsField();
    const list = [
      {label: 'Negrito', key: 'Ctrl+B', icon: 'B', cls: 'jarl-b', run: () => toggleInline('bold')},
      {label: 'Itálico', key: 'Ctrl+I', icon: 'I', cls: 'jarl-i', run: () => toggleInline('italic')},
      {label: 'Sublinhado', key: 'Ctrl+U', icon: 'U', cls: 'jarl-u', run: () => toggleInline('underline')},
      {label: 'Fonte', icon: 'Aa', sub: FONTS.map(([n, v]) => ({label: n, font: v, run: () => setProp('font-family', v)}))},
      {label: 'Tamanho', icon: 'tT', sub: SIZES.map(([n, v]) => ({label: n, run: () => setProp('font-size', v)}))},
      {label: 'Cor', icon: '◐', colors: true},
      {label: 'Borda', icon: '▢', sub: BORDERS.map(([n, v]) => ({label: n, run: () => setBox(v)}))},
      {label: 'Sombra', icon: '☼', sub: SHADOWS.map(([n, v]) => ({label: n, run: () => setProp('text-shadow', v)}))},
      {label: 'Limpar formatação', icon: '⌫', run: clearFormat},
    ];
    if (!blockLevel) {
      list.push({label: 'Link', key: 'Ctrl+K', icon: '🔗 Link', cls: 'jarl-tool-rotulo', link: true});
      if (S.values.length) list.push({label: 'Valores automáticos', icon: '{ }', values: true});
    }
    return list;
  }

  function blockActions() {
    const el = target();
    if (!el) return [];
    const info = blockInfo(el);
    if (info.mod) return [];
    const section = LANDMARKS.has(el.tagName);
    const models = S.models.filter(m => !!m.secao === section);
    const list = [
      {label: 'Mover para cima', key: 'Alt+↑', icon: '↑', run: () => moveBlock(el, 'cima')},
      {label: 'Mover para baixo', key: 'Alt+↓', icon: '↓', run: () => moveBlock(el, 'baixo')},
      {label: 'Duplicar', key: 'Ctrl+D', icon: '⧉', run: () => duplicateBlock(el),
       disabled: !info.duplicavel && !info.forcavel && (info.protegido || 'tem elementos com nome próprio')},
    ];
    if (models.length) {
      list.push({label: 'Adicionar depois', icon: '✚', sub: models.map(m =>
                  ({label: m.rotulo, run: () => insertModel(el, m, 'depois')}))},
                {label: 'Adicionar antes', icon: '⤒', sub: models.map(m =>
                  ({label: m.rotulo, run: () => insertModel(el, m, 'antes')}))});
    }
    if (el.tagName === 'A') list.push({label: 'Destino do link', icon: '🔗 Destino', cls: 'jarl-tool-rotulo', blockLink: true});
    list.push({label: 'Remover', key: 'Del', icon: '🗑', cls: 'jarl-danger', run: () => removeBlock(el),
               disabled: info.protegido && !info.forcavel && info.protegido});
    return list;
  }

  function toolButton(action) {
    const title = (action.key ? `${action.label} (${action.key})` : action.label) +
                  (typeof action.disabled === 'string' ? ` — ${action.disabled}` : '');
    const btn = $('button', {class: `jarl-tool ${action.cls || ''}`, title, disabled: !!action.disabled},
                  action.icon);
    if (action.run) btn.addEventListener('click', () => action.run());
    else btn.addEventListener('click', () => openPopover(action, btn));
    return btn;
  }

  function fillToolbar() {
    const bar = ui.toolbar;
    bar.replaceChildren();
    if (!S.active) {
      if (SHELL) SHELL.empty(bar); else bar.hidden = true;
      if (SHELL) SHELL.update(state());
      return;
    }
    const path = $('div', {class: 'jarl-crumbs'});
    const list = crumbs();
    list.slice().reverse().forEach((el, i) => {
      if (i) path.append($('span', {class: 'jarl-crumb-sep'}, '›'));
      path.append($('button', {class: 'jarl-crumb' + (el === target() ? ' jarl-crumb-on' : ''),
                               title: 'Selecionar este nível', on: {click: () => selectBlock(el)}},
                    blockLabel(el)));
    });
    const rowBlock = $('div', {class: 'jarl-row'}, path, $('span', {class: 'jarl-sep'}),
                       ...blockActions().map(toolButton));
    const format = formatActions();
    const rowFormat = $('div', {class: 'jarl-row'},
      ...(format.length ? format.map(toolButton)
                        : [$('span', {class: 'jarl-hint'}, 'Só texto neste campo')]),
      $('span', {class: 'jarl-sep'}),
      $('button', {class: 'jarl-tool', title: 'Desfazer (Ctrl+Z)', on: {click: undo}}, '↶'),
      $('button', {class: 'jarl-tool', title: 'Refazer (Ctrl+Shift+Z)', on: {click: redo}}, '↷'),
      $('button', {class: 'jarl-tool jarl-done', title: 'Concluir (Esc)', on: {click: () => deactivate()}}, '✓'));
    bar.append(rowBlock, rowFormat);
    bar.hidden = false;
    positionToolbar();
    if (SHELL) SHELL.update(state());
  }

  function colorPicker(onPick) {
    const wrap = $('div', {class: 'jarl-colors'});
    for (const [name, value] of COLORS) {
      wrap.append($('button', {class: 'jarl-swatch', title: name, style: `background:${value}`,
                               on: {click: () => onPick(value)}}));
    }
    const custom = $('input', {type: 'color', value: '#c8a45c', title: 'Outra cor'});
    custom.addEventListener('mousedown', rememberSelection);
    custom.addEventListener('change', () => onPick(custom.value));
    wrap.append(custom, $('button', {class: 'jarl-item jarl-small', on: {click: () => onPick('')}}, 'Cor padrão'));
    return wrap;
  }

  function valuesLegend(onPick) {
    // The legend of tags: what each prints today, and a click inserts it.
    const wrap = $('div', {class: 'jarl-values'},
      $('div', {class: 'jarl-values-head'}, 'Valores automáticos'),
      $('div', {class: 'jarl-values-help'},
        'Mudam sozinhos quando o modpack muda. Clique para inserir onde está o cursor.'));
    for (const v of S.values) {
      const asText = v.uso !== 'link';
      wrap.append($('button', {class: 'jarl-item jarl-value', disabled: !asText,
                               title: v.descricao, on: {click: () => onPick(v.chave)}},
        $('span', {class: 'jarl-chip jarl-chip-demo'}, v.rotulo),
        $('span', {class: 'jarl-value-now'}, asText ? (v.valor ? `hoje: ${v.valor}` : '') : 'só em links'),
        $('small', {class: 'jarl-value-desc'}, v.descricao)));
    }
    return wrap;
  }

  function normalizeHref(raw) {
    // What people type into a link box, made into an address: "discord.gg/x" is a
    // site, "nome@x.com" is an e-mail, "#x" and "/wiki/" stay as they are.
    const v = (raw || '').trim();
    if (!v) return '';
    if (/^(https?:\/\/|\/|#|mailto:|@@[A-Z_]+@@$)/i.test(v)) return v;
    if (/^[\w.+-]+@[\w-]+(\.[\w-]+)+$/.test(v)) return 'mailto:' + v;
    if (/^(www\.)?[\w-]+(\.[\w-]+)+(\/\S*)?$/i.test(v)) return 'https://' + v;
    return v;
  }
  const isExternal = href => /^https?:\/\//i.test(href) && !href.startsWith(location.origin);

  function linkForm({title = 'Link', href, newTab, text, withText, canRemove, onApply, onRemove}) {
    const textInput = withText ? $('input', {type: 'text', class: 'jarl-input jarl-input-texto', value: text || '',
                                             placeholder: 'Texto que aparece na página'}) : null;
    const input = $('input', {type: 'text', class: 'jarl-input', value: href || '',
                              placeholder: 'Cole um endereço ou escolha abaixo'});
    const tab = $('input', {type: 'checkbox'});
    tab.checked = !!newTab;
    let tabTouched = false;
    tab.addEventListener('change', () => { tabTouched = true; });
    const hint = $('div', {class: 'jarl-link-tipo'});
    const describe = () => {
      const h = normalizeHref(input.value);
      hint.textContent = !h ? '' : h.startsWith('#') ? 'Vai para uma seção desta página'
        : h.startsWith('mailto:') ? 'Abre o programa de e-mail'
        : /^@@/.test(h) ? 'Endereço automático (muda sozinho)'
        : h.startsWith('/') ? 'Página deste site' : isExternal(h) ? 'Site externo' : 'Endereço incompleto';
      if (!tabTouched) tab.checked = isExternal(h) || /^@@/.test(h) ? true : (newTab && h === href);
    };
    input.addEventListener('input', describe);
    const apply = () => {
      const h = normalizeHref(input.value);
      if (!validHref(h)) { toast('Esse endereço não parece um link. Ex.: https://site.com, /wiki/ ou #secao.', 'erro'); return; }
      const t = textInput ? textInput.value.trim() : '';
      if (textInput && !t && !text) { toast('Escreva o texto do link.', 'erro'); textInput.focus(); return; }
      onApply(h, tab.checked, t);
    };
    for (const el of [input, textInput]) {
      if (el) el.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); apply(); } });
    }
    // Destinations: this page's sections, the site's pages and their sections, automatic ones.
    const search = $('input', {type: 'search', class: 'jarl-input jarl-input-busca', placeholder: 'Procurar destino…'});
    const picks = $('div', {class: 'jarl-picks'});
    const all = [...S.destinations,
      ...S.values.filter(v => v.uso === 'link').map(v => ({grupo: 'Automáticos', rotulo: v.rotulo,
                                                            href: `@@${v.chave}@@`, descricao: v.descricao}))];
    const draw = () => {
      const q = squash(search.value).toLowerCase();
      const groups = {};
      for (const d of all) {
        if (q && !`${d.grupo} ${d.rotulo} ${d.href}`.toLowerCase().includes(q)) continue;
        (groups[d.grupo || 'Destinos'] ||= []).push(d);
      }
      picks.replaceChildren(...Object.entries(groups).flatMap(([g, list]) => [
        $('div', {class: 'jarl-menu-group'}, g),
        ...list.map(d => $('button', {class: 'jarl-item jarl-small', title: d.descricao || d.href,
          on: {click: () => {
            input.value = d.href;
            if (textInput && !textInput.value.trim()) textInput.value = d.rotulo.replace(/ \(topo da página\)$/, '');
            describe();
          }}}, d.rotulo, $('kbd', {}, d.href.startsWith('@@') ? 'automático' : d.href)))]));
      if (!picks.children.length) picks.append($('div', {class: 'jarl-values-help'}, 'Nada com esse nome. Para um site de fora, cole o endereço no campo acima.'));
    };
    search.addEventListener('input', draw);
    draw();
    describe();
    const test = $('button', {class: 'jarl-btn', title: 'Abrir o destino numa aba nova, para conferir',
      on: {click: () => {
        const h = normalizeHref(input.value);
        if (!validHref(h)) return;
        window.open(h.startsWith('#') ? location.pathname + h : linkValue(h), '_blank', 'noopener');
      }}}, 'Testar');
    const wrap = $('div', {class: 'jarl-linkform'},
      $('div', {class: 'jarl-values-head'}, title),
      textInput ? $('label', {class: 'jarl-rot'}, 'Texto') : null, textInput,
      $('label', {class: 'jarl-rot'}, 'Endereço'), input, hint,
      $('label', {class: 'jarl-check'}, tab, ' abrir em nova aba'),
      $('label', {class: 'jarl-rot'}, 'Destinos do site'), search, picks,
      $('div', {class: 'jarl-actions'},
        canRemove ? $('button', {class: 'jarl-btn', on: {click: onRemove}}, 'Remover link') : null,
        test,
        $('button', {class: 'jarl-btn jarl-primary', on: {click: apply}}, 'Aplicar')));
    setTimeout(() => (textInput && !textInput.value ? textInput : input).focus(), 30);
    return wrap;
  }

  function popoverBody(action, close) {
    if (action.values) return valuesLegend(name => { insertMarker(name); close(); });
    if (action.colors) return colorPicker(v => { setProp('color', v); close(); });
    if (action.link) return inlineLinkForm(close);
    if (action.blockLink) {
      const el = target();
      return linkForm({href: el.dataset.jarlHref || el.getAttribute('href'),
                       newTab: el.getAttribute('target') === '_blank',
                       onApply: (href, tab) => { setBlockLink(el, href, tab); close(); }});
    }
    return $('div', {}, action.sub.map(item =>
      $('button', {class: 'jarl-item', style: item.font ? `font-family:${item.font}` : null,
                   on: {click: () => { item.run(); close(); }}}, item.label)));
  }

  function openPopover(action, anchor) {
    closeMenus();
    rememberSelection();
    const pop = $('div', {class: 'jarl-menu jarl-pop', 'data-jarl-ui': ''});
    pop.addEventListener('mousedown', e => { if (!['INPUT', 'LABEL'].includes(e.target.tagName)) e.preventDefault(); });
    pop.append(popoverBody(action, closeMenus));
    H.body.append(pop);
    const r = anchor.getBoundingClientRect();
    place(pop, r.left, r.bottom + 4);
    ui.pop = pop;
  }

  function place(box, x, y) {
    box.hidden = false;
    box.style.left = '0px';
    box.style.top = '0px';
    const w = box.offsetWidth, h = box.offsetHeight;
    box.style.left = Math.max(8, Math.min(x, innerWidth - w - 8)) + 'px';
    box.style.top = Math.max(8, Math.min(y, innerHeight - h - 8)) + 'px';
  }

  function closeMenus() {
    ui.menu.hidden = true;
    if (ui.pop) { ui.pop.remove(); ui.pop = null; }
  }

  function contextMenu(e) {
    if (!S.editing || e.target.closest('[data-jarl-ui]')) return;
    e.preventDefault();
    const el = e.target.closest('.jarl-ed');
    if (el && tokenOf.get(el) !== S.active) activate(tokenOf.get(el));
    const field = S.active && S.fields.get(S.active);
    const menu = ui.menu;
    menu.replaceChildren();
    const item = (label, run, key, disabled) => $('button', {class: 'jarl-item', disabled: !!disabled,
      title: typeof disabled === 'string' ? disabled : null,
      on: {click: () => { closeMenus(); run(); }}}, label, key ? $('kbd', {}, key) : null);
    const sep = () => $('div', {class: 'jarl-line'});
    const withSub = action => {
      const sub = $('div', {class: 'jarl-menu jarl-sub', 'data-jarl-ui': ''}, popoverBody(action, closeMenus));
      sub.addEventListener('mousedown', ev => { if (!['INPUT', 'LABEL'].includes(ev.target.tagName)) ev.preventDefault(); });
      return $('div', {class: 'jarl-item jarl-has-sub'}, action.label, $('span', {class: 'jarl-arrow'}, '▸'), sub);
    };

    if (field) {
      menu.append($('div', {class: 'jarl-menu-title'}, blockLabel(target()) + ' · ' +
                    (field.rotulo || field.texto || '').slice(0, 40)));
      const levels = crumbs();
      if (levels.length > 1) {
        menu.append(withSub({label: 'Selecionar', sub: levels.map(l =>
          ({label: (l === target() ? '● ' : '') + blockLabel(l), run: () => selectBlock(l)}))}));
      }
      for (const action of blockActions()) {
        menu.append(action.run ? item(action.label, action.run, action.key, action.disabled) : withSub(action));
      }
      menu.append(sep());
      for (const action of formatActions()) {
        menu.append(action.run ? item(action.label, action.run, action.key) : withSub(action));
      }
      menu.append(sep(),
        item('Recortar', () => document.execCommand('cut'), 'Ctrl+X'),
        item('Copiar', () => document.execCommand('copy'), 'Ctrl+C'),
        item('Colar como texto', pasteFromClipboard, 'Ctrl+V'),
        sep());
    }
    const n = pendingCount();
    menu.append(
      item('Desfazer', undo, 'Ctrl+Z', !S.past.length && !S.typing),
      item('Refazer', redo, 'Ctrl+Shift+Z', !S.future.length),
      sep(),
      item(`Salvar alterações (${n})`, save, 'Ctrl+S', !n),
      item('Gerar link de prévia', makePreview, null, !n),
      item('Descartar alterações', discardAll, null, !n),
      sep(),
      item('Sair do modo edição', () => setEditing(false)),
      item('Abrir o painel do servidor', () => { location.href = `${ROOT}/`; }));
    menu.addEventListener('mousedown', ev => { if (!['INPUT', 'LABEL'].includes(ev.target.tagName)) ev.preventDefault(); });
    place(menu, e.clientX, e.clientY);
    // Submenus open to the side that has room.
    menu.classList.toggle('jarl-left', e.clientX > innerWidth - 560);
  }

  async function pasteFromClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      restoreSelection();
      document.execCommand('insertText', false, text);
    } catch {
      toast('O navegador não liberou a área de transferência; use Ctrl+V.', 'erro');
    }
  }

  // ------------------------------------------------------------ selection
  function rememberSelection() {
    const sel = getSelection();
    const el = S.active && S.elements.get(S.active);
    if (sel.rangeCount && el && el.contains(sel.getRangeAt(0).commonAncestorContainer)) {
      S.savedRange = sel.getRangeAt(0).cloneRange();
    }
  }
  function restoreSelection() {
    const el = S.active && S.elements.get(S.active);
    if (!el) return null;
    const sel = getSelection();
    if (document.activeElement !== el) el.focus({preventScroll: true});
    if (S.savedRange && el.contains(S.savedRange.commonAncestorContainer)) {
      sel.removeAllRanges();
      sel.addRange(S.savedRange);
    }
    return sel.rangeCount && el.contains(sel.getRangeAt(0).commonAncestorContainer) ? sel.getRangeAt(0) : null;
  }
  const hasSelection = () => {
    if (!targetIsField()) return null;
    const r = restoreSelection();
    return r && !r.collapsed ? r : null;
  };

  // ------------------------------------------------------------ formatting
  function restyle(mutate) {
    // Style of the selected level: the field (its own history step) or a whole
    // block (a structural step, saved as an 'estilo' operation).
    const el = target();
    if (!el) return;
    if (targetIsField()) {
      change(() => {
        const map = parseStyle(el.getAttribute('style'));
        mutate(map, el);
        map.delete('display');
        writeStyle(el, styleText(map));
      });
      return;
    }
    const before = el.getAttribute('style') || '';
    const map = parseStyle(before);
    mutate(map, el);
    map.delete('display');
    const after = styleText(map);
    if (after === squash(before)) return;
    writeStyle(el, after);
    pushOp({op: 'estilo', alvo: el.dataset.bloco, estilo: after},
           () => writeStyle(el, before), () => writeStyle(el, after), el);
  }

  function followInside(root, name, value) {
    // Inner pieces with their own stylesheet color (strong, links) follow the new one.
    if (!INHERITED.has(name)) return;
    root.querySelectorAll('*').forEach(inner => {
      if (inner.closest('[data-lock],[data-marker]') || inner.tagName === 'svg') return;
      if (value) inner.style.setProperty(name, 'inherit');
      else if (inner.style.getPropertyValue(name) === 'inherit') inner.style.removeProperty(name);
      if (!inner.getAttribute('style')) inner.removeAttribute('style');
    });
  }

  function toggleInline(command) {
    if (hasSelection()) {
      change(() => { document.execCommand('styleWithCSS', false, false); document.execCommand(command); });
      return;
    }
    const props = {bold: ['font-weight', 'bold', 'normal'], italic: ['font-style', 'italic', 'normal'],
                   underline: ['text-decoration', 'underline', 'none']}[command];
    restyle((map, el) => {
      const cs = getComputedStyle(el);
      const current = props[0] === 'font-weight' ? cs.fontWeight
        : props[0] === 'font-style' ? cs.fontStyle : cs.textDecorationLine;
      const on = props[0] === 'font-weight' ? Number(current) >= 600 || current === 'bold'
                                            : current.includes(props[1]);
      map.set(props[0], on ? props[2] : props[1]);
    });
  }

  function setProp(name, value) {
    const range = hasSelection();
    if (range) {
      change(() => {
        const span = document.createElement('span');
        if (value) span.style.setProperty(name, value);
        span.append(range.extractContents());
        span.querySelectorAll('[style]').forEach(inner => inner.style.removeProperty(name));
        followInside(span, name, value);
        range.insertNode(span);
        const sel = getSelection();
        sel.removeAllRanges();
        const again = document.createRange();
        again.selectNodeContents(span);
        sel.addRange(again);
        S.savedRange = again.cloneRange();
      });
      return;
    }
    restyle((map, el) => {
      if (value) map.set(name, value); else map.delete(name);
      if (isField(el)) followInside(el, name, value);
    });
  }

  function setBox(values) {
    restyle((map, el) => {
      for (const key of BOX_KEYS) map.delete(key);
      if (values) {
        for (const [k, v] of Object.entries(values)) map.set(k, v);
        // A border around inline text needs a box to sit on.
        if (getComputedStyle(el).display === 'inline') map.set('display', 'inline-block');
      }
    });
  }

  function clearFormat() {
    if (hasSelection()) { change(() => document.execCommand('removeFormat')); return; }
    restyle((map, el) => {
      map.clear();
      if (isField(el)) for (const name of INHERITED) followInside(el, name, '');
    });
  }

  function insertMarker(name) {
    const spec = S.values.find(v => v.chave === name);
    if (!spec || !S.active) { toast('Clique primeiro no trecho onde o valor deve entrar.', 'erro'); return; }
    if (S.fields.get(S.active).tag === 'mod') { toast('Descrição de mod não aceita valores automáticos.', 'erro'); return; }
    if (!targetIsField()) selectBlock(S.elements.get(S.active));
    change(() => {
      const el = S.elements.get(S.active);
      let range = restoreSelection();
      if (!range) { range = document.createRange(); range.selectNodeContents(el); range.collapse(false); }
      const chip = $('span', {'data-marker': name}, spec.rotulo);
      range.deleteContents();
      range.insertNode(chip);
      lockChips(el);
      caretAfter(chip);
    });
  }

  function caretAfter(node) {
    const after = document.createRange();
    after.setStartAfter(node);
    after.collapse(true);
    const sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(after);
    S.savedRange = after.cloneRange();
  }

  // ------------------------------------------------------------ links
  function linkValue(href) {
    // A tag as destination shows its real address in the draft.
    const tag = /^@@([A-Z_]+)@@$/.exec(href || '');
    const spec = tag && S.values.find(v => v.chave === tag[1]);
    return spec ? spec.valor : href;
  }
  const validHref = href => /^(https?:\/\/|\/|#|mailto:|@@[A-Z_]+@@$)/i.test(href);

  function inlineLinkForm(close) {
    const el = S.elements.get(S.active);
    // The field itself is a link (a button, a menu entry): edit where it points.
    if (el.tagName === 'A') {
      return linkForm({title: 'Destino deste link', href: el.dataset.jarlHref || el.getAttribute('href'),
                       newTab: el.getAttribute('target') === '_blank',
                       onApply: (href, tab) => { setBlockLink(el, href, tab); close(); }});
    }
    const range = restoreSelection();
    const node = range && (range.commonAncestorContainer.nodeType === 1
      ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement);
    const current = node && node.closest('a');
    const inside = current && el.contains(current) ? current : null;
    const selected = range && !range.collapsed ? squash(range.toString()) : '';
    return linkForm({
      title: inside ? 'Editar link' : selected ? 'Transformar em link' : 'Novo link',
      href: inside ? (inside.dataset.jarlHref || inside.getAttribute('href')) : '',
      newTab: inside ? inside.getAttribute('target') === '_blank' : false,
      // With text selected, that text becomes the link; otherwise the link is new text.
      withText: !selected || !!inside,
      text: inside ? squash(inside.textContent) : '',
      canRemove: !!inside,
      onApply: (href, tab, text) => {
        change(() => {
          let a = inside;
          if (!a) {
            a = document.createElement('a');
            let at = restoreSelection();
            if (!at) { at = document.createRange(); at.selectNodeContents(el); at.collapse(false); }
            let space = false;
            if (!at.collapsed) a.append(at.extractContents());
            else {
              a.textContent = text;
              // New text right after a word gets a space, so it does not glue to it.
              const prev = at.startContainer.nodeType === 3 ? at.startContainer.data[at.startOffset - 1] : null;
              space = !!prev && !/\s/.test(prev);
            }
            at.insertNode(a);
            if (space) a.before(document.createTextNode(' '));
          } else if (text && text !== squash(a.textContent)) {
            a.textContent = text;
          }
          a.setAttribute('href', href);
          if (tab) { a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener'); }
          else { a.removeAttribute('target'); a.removeAttribute('rel'); }
          caretAfter(a);
        });
        close();
        toast(inside ? 'Link atualizado.' : 'Link criado. Ctrl+Z desfaz.');
      },
      onRemove: () => {
        change(() => { inside.replaceWith(...inside.childNodes); });
        close();
      },
    });
  }

  function setBlockLink(el, href, newTab) {
    if (!validHref(href)) { toast('Use um endereço que comece com https://, / ou #.', 'erro'); return; }
    const before = {href: el.getAttribute('href'), tag: el.dataset.jarlHref, target: el.getAttribute('target'),
                    rel: el.getAttribute('rel')};
    const put = (h, shown, t, r) => {
      if (shown != null) el.setAttribute('href', shown); else el.removeAttribute('href');
      if (h) el.dataset.jarlHref = h; else delete el.dataset.jarlHref;
      if (t) el.setAttribute('target', t); else el.removeAttribute('target');
      if (r) el.setAttribute('rel', r); else el.removeAttribute('rel');
    };
    const tag = /^@@[A-Z_]+@@$/.test(href) ? href : '';
    const apply = () => put(tag, linkValue(href), newTab ? '_blank' : null, newTab ? 'noopener' : null);
    apply();
    pushOp({op: 'link', alvo: blockToken(el), href, nova_aba: newTab},
           () => put(before.tag, before.href, before.target, before.rel), apply, el);
  }

  // ------------------------------------------------------------ structure
  function pushOp(op, undoFn, redoFn, focusEl) {
    closeTyping();
    S.past.push({kind: 'op', op, undo: undoFn, redo: redoFn, focus: focusEl});
    S.future = [];
    fillToolbar();
    refreshDock();
  }

  function structuralSiblings(el) {
    return [...el.parentElement.children].filter(c => !OPAQUE.has(c.tagName.toUpperCase()) || c === el)
      .filter(c => !c.closest('[data-jarl-ui]'));
  }

  function swapNodes(a, b) {
    const mark = document.createComment('jarl');
    a.replaceWith(mark);
    b.replaceWith(a);
    mark.replaceWith(b);
  }

  function moveBlock(el, direction) {
    const siblings = structuralSiblings(el);
    const other = siblings[siblings.indexOf(el) + (direction === 'cima' ? -1 : 1)];
    if (!other) { toast('Esse bloco já está no limite.', 'erro'); return; }
    swapNodes(el, other);
    pushOp({op: 'mover', alvo: blockToken(el), direcao: direction},
           () => swapNodes(el, other), () => swapNodes(el, other), el);
    el.scrollIntoView({block: 'nearest', behavior: 'smooth'});
  }

  function confirmForce(info, what) {
    return confirm(`Atenção: esse bloco ${info.protegido}.\n\n${what} pode fazer esses valores ` +
                   'pararem de atualizar ou quebrar essa parte da página. Dá para desfazer antes de ' +
                   'salvar (Ctrl+Z).\n\nContinuar mesmo assim?');
  }

  function removeBlock(el) {
    const info = blockInfo(el);
    let force = false;
    if (info.protegido) {
      if (!info.forcavel) { toast(`Esse bloco não pode ser removido: ${info.protegido}.`, 'erro'); return; }
      if (!confirmForce(info, 'Remover')) return;
      force = true;
    }
    const parent = el.parentNode, next = el.nextSibling;
    if (S.active && el.contains(S.elements.get(S.active))) deactivate();
    el.remove();
    pushOp({op: 'remover', alvo: blockToken(el), ...(force ? {forcar: true} : {})},
           () => parent.insertBefore(el, next), () => el.remove(), null);
    const hint = el.id && document.querySelector(`a[href="#${CSS.escape(el.id)}"]`);
    toast(hint ? 'Bloco removido. O link para ele no menu continua; remova-o também se quiser.'
               : 'Bloco removido. Ctrl+Z desfaz.');
  }

  function registerNewFields(root, sourceOf) {
    // Fields born in this session: always sent whole when saving.
    for (const el of [root, ...root.querySelectorAll('[data-campo]')]) {
      if (!el.dataset || !el.dataset.campo) continue;
      const token = el.dataset.campo;
      const from = sourceOf(el);
      S.fields.set(token, {...from, token, hash: null, novo: true, travas: []});
      S.elements.set(token, el);
      tokenOf.set(el, token);
      S.created.add(token);
      S.swapped.add(token);
      S.base.set(token, {html: '', style: ''});
      el.classList.add('jarl-ed');
      lockChips(el);
    }
  }

  function cleanClone(el) {
    el.classList.remove('jarl-active', 'jarl-sel', 'jarl-changed');
    el.removeAttribute('contenteditable');
    el.querySelectorAll('.jarl-active,.jarl-sel,.jarl-changed').forEach(x =>
      x.classList.remove('jarl-active', 'jarl-sel', 'jarl-changed'));
  }

  function duplicateBlock(el, {quiet} = {}) {
    const info = blockInfo(el);
    let force = false;
    if (!info.duplicavel) {
      if (!info.forcavel) {
        toast(`Esse bloco não pode ser duplicado: ${info.protegido || 'tem elementos com nome próprio'}.`, 'erro');
        return;
      }
      if (!confirmForce(info, 'Duplicar')) return;
      force = true;
    }
    // The copy must carry the source form (tags as chips), not the printed values.
    for (const f of [el, ...el.querySelectorAll('[data-campo]')]) {
      const token = f.dataset && f.dataset.campo;
      if (token && S.fields.has(token)) swapIn(token);
    }
    const wasActive = S.active;
    if (wasActive && el.contains(S.elements.get(wasActive))) deactivate();
    const copy = el.cloneNode(true);
    cleanClone(copy);
    // Forced copy: inner names must stay unique, so the copy's inner parts lose theirs.
    if (force) copy.querySelectorAll('[id]').forEach(x => x.removeAttribute('id'));
    const tokens = {};
    for (const node of [copy, ...copy.querySelectorAll('[data-campo],[data-bloco]')]) {
      for (const attr of ['campo', 'bloco']) {
        const old = node.dataset[attr];
        if (!old) continue;
        tokens[old] = newToken();
        node.dataset[attr] = tokens[old];
        if (attr === 'bloco') S.blocks[tokens[old]] = {...(S.blocks[old] || {}), protegido: '', duplicavel: true};
      }
    }
    if (el.id) {
      tokens['#id'] = `${el.id.replace(/-\d+$/, '')}-${Math.random().toString(36).slice(2, 6)}`;
      copy.id = tokens['#id'];
    }
    el.after(copy);
    const oldOf = new Map(Object.entries(tokens).map(([o, n]) => [n, o]));
    registerNewFields(copy, node => S.fields.get(oldOf.get(node.dataset.campo)) || {});
    pushOp({op: 'duplicar', alvo: blockToken(el), tokens, ...(force ? {forcar: true} : {})},
           () => copy.remove(), () => el.after(copy), copy);
    if (quiet) return copy;
    const first = copy.dataset.campo ? copy : copy.querySelector('[data-campo]');
    if (first) activate(first.dataset.campo);
    if (LANDMARKS.has(copy.tagName) && copy.id) offerMenu(copy);
    else toast('Cópia criada logo abaixo. Edite à vontade; só vai ao ar quando salvar.');
    return copy;
  }

  function insertModel(el, model, position, live) {
    if (model.vivo && !live) {
      pickLive(key => insertModel(el, model, position, key));
      return;
    }
    const tokens = {};
    const html = model.html.replace(/\{([a-z0-9]+)\}/g, (_, key) => {
      if (key === 'id') return (tokens['#id'] ||= `secao-${newToken()}`);
      if (key === 'vivo') return (tokens.vivo = live);
      return (tokens[key] ||= newToken());
    });
    const tpl = document.createElement('template');
    tpl.innerHTML = html.trim();
    const node = tpl.content.firstElementChild;
    for (const b of [node, ...node.querySelectorAll('[data-bloco]')]) {
      if (b.dataset && b.dataset.bloco) S.blocks[b.dataset.bloco] = {protegido: '', duplicavel: !b.id, secao: !!model.secao};
    }
    if (position === 'antes') el.before(node); else el.after(node);
    registerNewFields(node, f => ({tag: f.tagName.toLowerCase(), tipo: 'texto', estilo: '',
                                   texto: f.textContent, html: f.innerHTML}));
    if (window.HeimdallVivo) window.HeimdallVivo.paint();
    pushOp({op: 'inserir', alvo: blockToken(el), posicao: position, modelo: model.chave, tokens},
           () => node.remove(), () => (position === 'antes' ? el.before(node) : el.after(node)), node);
    const first = node.dataset.campo ? node : node.querySelector('[data-campo]');
    if (first) {
      activate(first.dataset.campo);
      const r = document.createRange();
      r.selectNodeContents(first);
      getSelection().removeAllRanges();
      getSelection().addRange(r);
    }
    node.scrollIntoView({block: 'center', behavior: 'smooth'});
    if (model.secao) offerMenu(node);
    if (model.abrirLink) openLinkOn(node.querySelector('a') || node);
  }

  function openLinkOn(anchor) {
    // Puts the caret inside the new link and opens the link tool on it.
    const field = anchor.closest('.jarl-ed');
    if (!field) return;
    activate(tokenOf.get(field));
    const r = document.createRange();
    r.selectNodeContents(anchor);
    r.collapse(true);
    getSelection().removeAllRanges();
    getSelection().addRange(r);
    S.savedRange = r.cloneRange();
    setTimeout(() => {
      const btn = [...ui.toolbar.querySelectorAll('.jarl-tool')].find(b => b.textContent.startsWith('🔗'));
      if (btn) btn.click();
    }, 60);
  }

  // ------------------------------------------------------------ live data
  const catalog = () => (window.HeimdallVivo && window.HeimdallVivo.CATALOG) || {};
  const liveValue = key => { try { return catalog()[key].valor(); } catch { return '—'; } };

  function pickLive(onPick, x, y) {
    // A menu of every live value, grouped, with what it shows right now.
    closeMenus();
    const items = Object.entries(catalog());
    if (!items.length) { toast('Esta página ainda não carrega os dados ao vivo (vivo.js).', 'erro'); return; }
    const menu = ui.menu;
    menu.replaceChildren($('div', {class: 'jarl-menu-title'}, 'Qual dado ao vivo?'));
    const groups = {};
    for (const [key, item] of items) (groups[item.grupo] ||= []).push([key, item]);
    for (const [group, list] of Object.entries(groups)) {
      menu.append($('div', {class: 'jarl-menu-group'}, group));
      for (const [key, item] of list) {
        menu.append($('button', {class: 'jarl-item', title: item.descricao,
          on: {click: () => { closeMenus(); onPick(key); }}}, item.rotulo, $('kbd', {}, liveValue(key))));
      }
    }
    menu.addEventListener('mousedown', ev => ev.preventDefault());
    place(menu, x ?? innerWidth / 2 - 140, y ?? 80);
  }

  function insertLive(key, range) {
    // A live value inside the text being edited: a chip the page fills in.
    const field = S.active && S.fields.get(S.active);
    if (!field || field.tag === 'mod') { toast('Clique primeiro no texto onde o dado deve entrar.', 'erro'); return; }
    if (!targetIsField()) selectBlock(S.elements.get(S.active));
    change(() => {
      const el = S.elements.get(S.active);
      let r = range || restoreSelection();
      if (!r || !el.contains(r.commonAncestorContainer)) {
        r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
      }
      const chip = document.createElement('span');
      chip.dataset.vivo = key;
      chip.textContent = liveValue(key);
      r.deleteContents();
      r.insertNode(chip);
      lockChips(el);
      caretAfter(chip);
    });
  }

  // ------------------------------------------------------------ drag and drop
  // The full-screen editor's sidebar sets SHELL.dragging = {tipo: 'modelo'|'vivo', chave};
  // the page shows where it would land and does the insert.
  let dropLine = null, dropAt = null;
  function showDrop(rect, where, inline) {
    if (!dropLine) { dropLine = document.createElement('div'); dropLine.className = 'jarl-drop'; document.body.append(dropLine); }
    dropLine.hidden = false;
    dropLine.classList.toggle('jarl-drop-caret', !!inline);
    if (inline) {
      Object.assign(dropLine.style, {left: rect.left + scrollX - 1 + 'px', top: rect.top + scrollY + 'px',
                                     width: '3px', height: Math.max(rect.height, 16) + 'px'});
    } else {
      const y = where === 'antes' ? rect.top - 4 : rect.bottom + 2;
      Object.assign(dropLine.style, {left: rect.left + scrollX + 'px', top: y + scrollY + 'px',
                                     width: rect.width + 'px', height: '3px'});
    }
  }
  function hideDrop() { if (dropLine) dropLine.hidden = true; dropAt = null; }

  function dropTarget(x, y, item) {
    const under = document.elementFromPoint(x, y);
    if (!under || under.closest('[data-jarl-ui]')) return null;
    const model = item.tipo === 'modelo' && S.models.find(m => m.chave === item.chave);
    // A live value over editable text goes into the text, at the caret.
    if (item.tipo === 'vivo') {
      const field = under.closest('.jarl-ed');
      const info = field && S.fields.get(tokenOf.get(field));
      if (info && info.tag !== 'mod' && !info.simples) {
        const caret = document.caretRangeFromPoint ? document.caretRangeFromPoint(x, y) : null;
        if (caret && field.contains(caret.startContainer)) {
          const rects = caret.getClientRects();
          return {kind: 'inline', field, range: caret, rect: rects[0] || field.getBoundingClientRect()};
        }
      }
    }
    const wantSection = model && model.secao;
    let el = under;
    for (; el && el !== document.body; el = el.parentElement) {
      if (!(el.dataset.bloco || (el.dataset.campo && tokenOf.has(el)))) continue;
      if (wantSection ? LANDMARKS.has(el.tagName) : !LANDMARKS.has(el.tagName)) break;
    }
    if (!el || el === document.body) return null;
    const rect = el.getBoundingClientRect();
    return {kind: 'block', el, rect, where: y < rect.top + rect.height / 2 ? 'antes' : 'depois'};
  }

  document.addEventListener('dragover', e => {
    const item = SHELL && SHELL.dragging;
    if (!S.editing || !item) return;
    const t = dropTarget(e.clientX, e.clientY, item);
    if (!t) { hideDrop(); return; }
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    dropAt = t;
    showDrop(t.rect, t.where, t.kind === 'inline');
  });
  document.addEventListener('dragleave', e => { if (!e.relatedTarget) hideDrop(); });
  document.addEventListener('drop', e => {
    const item = SHELL && SHELL.dragging, t = dropAt;
    hideDrop();
    if (!S.editing || !item || !t) return;
    e.preventDefault();
    SHELL.dragging = null;
    if (t.kind === 'inline') {
      activate(tokenOf.get(t.field));
      insertLive(item.chave, t.range);
      return;
    }
    if (item.tipo === 'vivo') {
      // Dropped between blocks: a new card built around that value.
      const card = S.models.find(m => m.vivo);
      if (!card) { toast('Solte o dado dentro de um texto.', 'erro'); return; }
      insertModel(t.el, card, t.where, item.chave);
      return;
    }
    const model = S.models.find(m => m.chave === item.chave);
    if (model) {
      if (model.vivo) pickLive(key => insertModel(t.el, model, t.where, key), e.clientX, e.clientY);
      else insertModel(t.el, model, t.where);
    }
  });

  function insertAfterSelection(chave) {
    // Clicking an element in the sidebar (instead of dragging) adds it after the
    // selected block, or after the section when a section model is picked.
    const model = S.models.find(m => m.chave === chave);
    let el = target();
    if (!model) return;
    if (!el) { toast('Selecione primeiro um trecho da página, ou arraste o elemento até lá.', 'erro'); return; }
    if (model.secao) el = el.closest('section,header,footer,nav,aside') || el;
    else if (LANDMARKS.has(el.tagName)) { toast('Escolha um bloco dentro da seção, ou arraste até o lugar.', 'erro'); return; }
    insertModel(el, model, 'depois');
  }

  // ------------------------------------------------------------ state for the shell
  function state() {
    const el = target();
    return {
      page: S.page, editing: S.editing, pending: pendingCount(),
      canUndo: !!(S.past.length || S.typing), canRedo: !!S.future.length, busy: S.busy,
      selected: el ? blockLabel(el) : '',
      sections: sectionsList(),
      models: S.models, values: S.values,
    };
  }
  function sectionsList() {
    return [...document.querySelectorAll('[data-bloco]')]
      .filter(el => LANDMARKS.has(el.tagName) && el.querySelector('.jarl-ed'))
      .map(el => ({token: el.dataset.bloco, label: blockLabel(el), id: el.id || ''}));
  }
  function selectSection(token) {
    const sec = document.querySelector(`[data-bloco="${CSS.escape(token)}"]`);
    if (!sec) return;
    const first = sec.querySelector('.jarl-ed');
    if (first) activate(tokenOf.get(first));
    selectBlock(sec);
    sec.scrollIntoView({block: 'start', behavior: 'smooth'});
  }

  // ------------------------------------------------------------ history
  const snapshot = token => {
    const el = S.elements.get(token);
    return {html: el.innerHTML, style: el.getAttribute('style') || ''};
  };

  function restore(token, snap) {
    const el = S.elements.get(token);
    el.innerHTML = snap.html;
    writeStyle(el, snap.style);
    lockChips(el);
  }

  const alive = token => { const el = S.elements.get(token); return !!el && document.contains(el); };
  function fieldChanged(token) {
    if (!S.swapped.has(token) || !alive(token)) return false;
    if (S.created.has(token)) return true;
    const now = snapshot(token), base = S.base.get(token);
    return squash(now.html) !== squash(base.html) || squash(now.style) !== squash(base.style);
  }
  const changedFields = () => [...S.swapped].filter(fieldChanged);
  // Emptying a text means "take it out": saved as a removal, not as an empty field.
  const isEmpty = token => {
    const el = S.elements.get(token);
    return !!el && !squash(el.textContent) && !el.querySelector('[data-marker],[data-lock],[data-vivo]');
  };
  const pastOps = () => S.past.filter(s => s.kind === 'op').map(s => s.op);
  const pendingCount = () => changedFields().filter(t => !S.created.has(t)).length + pastOps().length;

  function closeTyping() {
    if (!S.typing) return;
    clearTimeout(S.typing.timer);
    const {token, before} = S.typing;
    S.typing = null;
    const after = snapshot(token);
    if (after.html !== before.html || after.style !== before.style) {
      S.past.push({kind: 'campo', token, before, after});
      S.future = [];
    }
    if (S.active === token) S.stable = after;
    refreshDock();
  }

  function change(fn) {
    if (!S.active) return;
    closeTyping();
    const token = S.active;
    const before = snapshot(token);
    S.applying = true;
    try { fn(); } finally { S.applying = false; }
    const after = snapshot(token);
    S.stable = after;
    if (after.html !== before.html || after.style !== before.style) {
      S.past.push({kind: 'campo', token, before, after});
      S.future = [];
    }
    positionToolbar();
    refreshDock();
  }

  function onInput() {
    const token = S.active;
    if (!token || S.applying) return;
    if (!S.typing || S.typing.token !== token) {
      closeTyping();
      S.typing = {token, before: S.stable || snapshot(token)};
    }
    clearTimeout(S.typing.timer);
    S.typing.timer = setTimeout(closeTyping, 700);
    refreshDock();
  }

  function undo() {
    closeTyping();
    const step = S.past.pop();
    if (!step) return;
    S.future.push(step);
    if (step.kind === 'op') { deactivate(); step.undo(); afterHistory(step.focus); return; }
    restore(step.token, step.before);
    focusAfterHistory(step.token);
  }
  function redo() {
    closeTyping();
    const step = S.future.pop();
    if (!step) return;
    S.past.push(step);
    if (step.kind === 'op') { deactivate(); step.redo(); afterHistory(step.focus); return; }
    restore(step.token, step.after);
    focusAfterHistory(step.token);
  }
  function afterHistory(el) {
    if (el && document.contains(el)) el.scrollIntoView({block: 'nearest', behavior: 'smooth'});
    refreshDock();
  }
  function focusAfterHistory(token) {
    if (!alive(token)) { refreshDock(); return; }
    if (S.active !== token) activate(token, {keepContent: true});
    S.stable = snapshot(token);
    S.elements.get(token).scrollIntoView({block: 'nearest', behavior: 'smooth'});
    refreshDock();
  }

  // ------------------------------------------------------------ fields
  function lockChips(el) {
    el.querySelectorAll('[data-vivo]').forEach(chip => {
      const item = catalog()[chip.dataset.vivo];
      chip.contentEditable = 'false';
      chip.classList.add('jarl-chip', 'jarl-chip-vivo');
      chip.title = item ? `Ao vivo: ${item.rotulo}. ${item.descricao}` : 'Dado ao vivo';
    });
    el.querySelectorAll('[data-marker],[data-lock]').forEach(chip => {
      chip.contentEditable = 'false';
      if (chip.tagName.toLowerCase() !== 'svg') chip.classList.add('jarl-chip');
      if (chip.dataset.marker) {
        const spec = S.values.find(v => v.chave === chip.dataset.marker);
        chip.title = spec
          ? `${spec.rotulo}${spec.valor ? ` (hoje: ${spec.valor})` : ''}. ${spec.descricao}`
          : 'Valor automático, preenchido pelo gerador da página';
      } else if (chip.tagName.toLowerCase() !== 'svg') {
        chip.title = 'Valor ao vivo, atualizado pelo próprio site';
      }
    });
  }

  function swapIn(token) {
    // The published text has build markers already filled in; the editor needs the
    // source form, with markers as chips. Live elements stay the real nodes, so the
    // page's own scripts keep updating them while you edit.
    if (S.swapped.has(token)) return;
    const el = S.elements.get(token);
    const field = S.fields.get(token);
    if (field.tag !== 'mod') {
      const live = (field.travas || []).map(id => id && document.getElementById(id));
      el.innerHTML = field.html;
      el.querySelectorAll('[data-lock]').forEach(chip => {
        const node = live[Number(chip.dataset.lock)];
        if (node) { node.dataset.lock = chip.dataset.lock; chip.replaceWith(node); }
      });
      lockChips(el);
    }
    S.swapped.add(token);
    S.base.set(token, snapshot(token));
  }

  function activate(token, {keepContent} = {}) {
    if (!token || !alive(token)) return;
    if (S.active === token) { selectBlock(S.elements.get(token)); return; }
    deactivate();
    const el = S.elements.get(token);
    if (!keepContent || !S.swapped.has(token)) swapIn(token);
    S.active = token;
    el.classList.add('jarl-active');
    el.contentEditable = 'true';
    el.spellcheck = true;
    el.addEventListener('input', onInput);
    S.block = null;
    selectBlock(el);
    el.focus({preventScroll: true});
    S.stable = snapshot(token);
  }

  function deactivate() {
    if (!S.active) { if (S.block) selectBlock(null); return; }
    closeTyping();
    const el = S.elements.get(S.active);
    el.removeAttribute('contenteditable');
    el.classList.remove('jarl-active');
    el.removeEventListener('input', onInput);
    const token = S.active;
    S.active = null;
    S.savedRange = null;
    if (S.block) S.block.classList.remove('jarl-sel');
    S.block = null;
    ui.toolbar.hidden = true;
    closeMenus();
    // Untouched fields go back to the published text (markers filled in again).
    if (!S.created.has(token) && !fieldChanged(token) &&
        !S.past.some(s => s.token === token) && !S.future.some(s => s.token === token)) {
      putBack(token);
    }
    refreshDock();
  }

  function putBack(token) {
    const el = S.elements.get(token);
    const orig = S.original.get(token);
    if (!el || !orig) return;
    const liveNodes = [...el.querySelectorAll('[data-lock]')].filter(n => n.id);
    el.innerHTML = orig.html;
    // Put the live nodes back where the published copy has their placeholders.
    for (const node of liveNodes) {
      const twin = el.querySelector('#' + CSS.escape(node.id));
      delete node.dataset.lock;
      if (twin) twin.replaceWith(node);
    }
    writeStyle(el, orig.style);
    S.swapped.delete(token);
    S.base.delete(token);
  }

  function positionToolbar() {
    // A ribbon pinned to the top of the window: floating over the field it would
    // cover the text just above it, which then could not be clicked.
    if (SHELL || !S.active || ui.toolbar.hidden) return;
    const bar = ui.toolbar;
    bar.style.top = '12px';
    bar.style.left = Math.max(8, (innerWidth - bar.offsetWidth) / 2) + 'px';
  }

  // ------------------------------------------------------------ edit mode
  async function loadFields() {
    const d = await api(`/api/site/campos?url=${encodeURIComponent(location.pathname)}`);
    S.page = d.pagina;
    S.values = d.valores || [];
    S.blocks = d.blocos || {};
    S.models = d.modelos || [];
    S.destinations = d.destinos || [];
    S.titles = {};
    S.fields.clear();
    S.elements.clear();
    for (const section of d.secoes) {
      if (section.ancora && section.id !== 'mods') S.titles[section.ancora] ||= section.titulo;
      for (const field of section.campos) {
        if (!field.token) continue;
        const el = field.tag === 'mod'
          ? document.querySelector(`[data-mod="${CSS.escape(field.token.slice(4))}"]`)
          : document.querySelector(`[data-campo="${CSS.escape(field.token)}"]`);
        if (!el) continue;
        S.fields.set(field.token, field);
        S.elements.set(field.token, el);
        tokenOf.set(el, field.token);
        S.original.set(field.token, {html: el.innerHTML, style: el.getAttribute('style') || ''});
      }
    }
    remapModFields();
  }

  function remapModFields() {
    for (const [token, field] of S.fields) {
      if (field.tag !== 'mod') continue;
      const el = document.querySelector(`[data-mod="${CSS.escape(token.slice(4))}"]`);
      if (!el) continue;
      S.elements.set(token, el);
      tokenOf.set(el, token);
      if (S.editing) el.classList.add('jarl-ed');
    }
  }
  document.addEventListener('heimdall:mods-rendered', remapModFields);

  function reloadKeepingMode(editing) {
    S.busy = true;   // no "unsaved changes" prompt: the reload is the discard
    if (editing) sessionStorage.setItem(EDITING_KEY, '1'); else sessionStorage.removeItem(EDITING_KEY);
    location.reload();
  }

  async function setEditing(on) {
    if (on === S.editing) return;
    if (!on) {
      const n = pendingCount();
      if (n) {
        if (!confirm(`Há ${n} ${n === 1 ? 'alteração não salva' : 'alterações não salvas'}. Sair e descartar?`)) return;
        reloadKeepingMode(false);
        return;
      }
      deactivate();
      for (const token of [...S.swapped]) putBack(token);
      for (const el of S.elements.values()) el.classList.remove('jarl-ed', 'jarl-changed');
      S.editing = false;
      document.documentElement.classList.remove('jarl-editing');
      sessionStorage.removeItem(EDITING_KEY);
      note('');
      refreshDock();
      return;
    }
    try {
      await loadFields();
    } catch (error) {
      if (error.expired) return signedOut();
      note(error.message);
      return;
    }
    if (S.page.somente_leitura) {
      note(S.page.somente_leitura);
      return;
    }
    S.editing = true;
    document.documentElement.classList.add('jarl-editing');
    for (const el of S.elements.values()) el.classList.add('jarl-ed');
    sessionStorage.setItem(EDITING_KEY, '1');
    note('');
    refreshDock();
    toast(`${S.elements.size} trechos editáveis. Clique para editar; a trilha no topo escolhe o bloco ` +
          'inteiro (seção, caixa, item) para mover, duplicar, adicionar ou remover.');
  }

  function discardAll() {
    const n = pendingCount();
    if (!n || !confirm(`Descartar ${n} ${n === 1 ? 'alteração' : 'alterações'}?`)) return;
    reloadKeepingMode(true);
  }

  function payload() {
    // What the panel needs: structural operations in order, then the final text of
    // every changed field. Emptied fields travel as removals.
    closeTyping();
    syncMenuLabels();
    const ops = pastOps();
    const emptied = changedFields().filter(t => isEmpty(t) && S.fields.get(t).tag !== 'mod');
    for (const token of emptied) ops.push({op: 'remover', alvo: token});
    const tokens = changedFields().filter(t => !emptied.includes(t));
    const changes = tokens.map(token => {
      const field = S.fields.get(token), now = snapshot(token), base = S.base.get(token);
      if (field.tag === 'mod') return {campo: token, hash: field.hash, html: S.elements.get(token).textContent};
      if (S.created.has(token)) return {campo: token, html: now.html, estilo: now.style};
      const item = {campo: token, hash: field.hash};
      if (squash(now.html) !== squash(base.html)) item.html = now.html;
      if (squash(now.style) !== squash(base.style)) item.estilo = now.style;
      return item;
    });
    return {url: location.pathname, operacoes: ops, alteracoes: changes};
  }

  async function save({skipChecks} = {}) {
    if (S.busy) return;
    const body = payload();
    if (!body.alteracoes.length && !body.operacoes.length) return;
    if (!skipChecks) {
      const issues = await audit();
      if (issues.length) { showIssues(issues); return; }
    }
    S.busy = true;
    refreshDock();
    if (ui.save) ui.save.classList.add('jarl-working');
    try {
      const d = await api('/api/site/gravar', body);
      toast(`${d.alterados} ${d.alterados === 1 ? 'alteração salva' : 'alterações salvas'} e publicadas. Recarregando…`);
      if (SHELL && SHELL.saved) SHELL.saved();
      setTimeout(() => reloadKeepingMode(true), 900);
    } catch (error) {
      S.busy = false;
      if (error.expired) return signedOut();
      toast(error.message, 'erro');
    } finally {
      if (ui.save) ui.save.classList.remove('jarl-working');
      refreshDock();
    }
  }

  // ------------------------------------------------------------ preview link
  async function makePreview() {
    const body = payload();
    if (!body.alteracoes.length && !body.operacoes.length) {
      toast('Não há alterações para mostrar: a prévia seria igual à página publicada.', 'erro');
      return;
    }
    toast('Montando a prévia…');
    try {
      const d = await api('/api/site/previa', body);
      const link = location.origin + d.endereco;
      const input = $('input', {class: 'jarl-input', value: link, readonly: true});
      showModal('Link de prévia', [
        $('p', {}, `Quem tiver este link vê a página com as suas alterações, antes de publicar. Vale por ${d.dias} dias; a página no ar não muda.`),
        input,
      ], [
        {label: 'Abrir', run: () => window.open(link, '_blank')},
        {label: 'Copiar link', primary: true, run: async close => {
          try { await navigator.clipboard.writeText(link); toast('Link copiado.'); close(); }
          catch { input.select(); toast('Selecionei o link: use Ctrl+C.', 'erro'); }
        }},
      ]);
    } catch (error) {
      if (error.expired) return signedOut();
      toast(error.message, 'erro');
    }
  }

  // ------------------------------------------------------------ modal
  function showModal(title, body, buttons) {
    const back = $('div', {class: 'jarl-modal-fundo', 'data-jarl-ui': ''});
    const close = () => back.remove();
    const box = $('div', {class: 'jarl-modal'},
      $('h3', {}, title), $('div', {class: 'jarl-modal-corpo'}, body),
      $('div', {class: 'jarl-actions'},
        $('button', {class: 'jarl-btn', on: {click: close}}, 'Fechar'),
        ...buttons.map(b => $('button', {class: 'jarl-btn' + (b.primary ? ' jarl-primary' : ''),
                                         on: {click: () => b.run(close)}}, b.label))));
    back.append(box);
    back.addEventListener('click', e => { if (e.target === back) close(); });
    H.body.append(back);
    return close;
  }

  // ------------------------------------------------------------ checks before saving
  function menusOfPage() {
    // A "section menu" is a nav whose links point at this page's sections.
    return [...document.querySelectorAll('nav')].filter(nav =>
      [...nav.querySelectorAll('a[href^="#"]')].filter(a => {
        const id = decodeURIComponent(a.getAttribute('href').slice(1));
        const el = id && document.getElementById(id);
        return el && LANDMARKS.has(el.tagName);
      }).length >= 2);
  }

  async function audit() {
    const issues = [];
    const inUi = el => el.closest('[data-jarl-ui]');
    // 1. links to anchors that are gone (a removed section left its menu entry behind)
    for (const a of document.querySelectorAll('a[href^="#"]')) {
      const id = decodeURIComponent(a.getAttribute('href').slice(1));
      if (!id || inUi(a) || document.getElementById(id)) continue;
      const own = isField(a) ? a : a.closest('.jarl-ed');
      const inMenu = !!a.closest('nav') && isField(a);
      issues.push({text: `O link “${squash(a.textContent) || id}” aponta para #${id}, que não existe mais na página.`,
                   el: a, fix: inMenu ? {label: 'Remover o link', run: () => removeBlock(a)} : null,
                   own});
    }
    // 2. new sections not in the section menu
    const menus = menusOfPage();
    if (menus.length) {
      for (const sec of document.querySelectorAll('section[id],header[id],footer[id],aside[id]')) {
        if (!sec.dataset.bloco || !S.newSections.has(sec)) continue;
        if (menus.some(m => m.querySelector(`a[href="#${CSS.escape(sec.id)}"]`))) continue;
        issues.push({text: `A seção nova “${sectionTitle(sec)}” não está no menu da página.`, el: sec,
                     fix: {label: 'Incluir no menu', run: () => addToMenu(sec)}});
      }
    }
    // 3. blocks left without any content
    for (const b of document.querySelectorAll('[data-bloco]')) {
      if (inUi(b) || b.closest('[hidden]')) continue;
      if (squash(b.textContent) || b.querySelector('img,svg,[data-vivo],[data-marker],input,button,iframe,video')) continue;
      issues.push({text: `${blockLabel(b)} ficou vazio.`, el: b,
                   fix: blockInfo(b).protegido ? null : {label: 'Remover', run: () => removeBlock(b)}});
    }
    // 4. live values (old style, by id) that left a text you edited: usually by accident
    for (const token of changedFields()) {
      const field = S.fields.get(token), el = S.elements.get(token);
      for (const id of (field.travas || []).filter(Boolean)) {
        if (el.querySelector('#' + CSS.escape(id))) continue;
        issues.push({text: `Um valor que se atualiza sozinho saiu do trecho “${squash(field.texto).slice(0, 50)}”. ` +
                           'Se foi sem querer, use Ctrl+Z; se foi de propósito, pode publicar.', el, fix: null});
      }
    }
    // 5. images with no description
    for (const img of document.querySelectorAll('img:not([alt])')) {
      if (inUi(img) || !img.closest('[data-bloco]')) continue;
      issues.push({text: 'Uma imagem está sem descrição (texto alternativo).', el: img, fix: null});
    }
    // 6. internal links that answer "not found" (only those touched in this session)
    const touched = [...S.swapped].filter(fieldChanged).map(t => S.elements.get(t));
    for (const step of S.past) if (step.kind === 'op' && step.op.op === 'link' && step.focus) touched.push(step.focus);
    const links = [];
    for (const el of touched) {
      if (!el || !document.contains(el)) continue;
      for (const a of el.tagName === 'A' ? [el] : el.querySelectorAll('a[href]')) links.push(a);
    }
    const seen = new Set();
    await Promise.all(links.slice(0, 20).map(async a => {
      const href = a.dataset.jarlHref || a.getAttribute('href') || '';
      if (!href.startsWith('/') || href.startsWith('//') || seen.has(href)) return;
      seen.add(href);
      try {
        const r = await fetch(href.split('#')[0], {method: 'HEAD', credentials: 'same-origin'});
        if (r.status === 404) issues.push({text: `O link “${squash(a.textContent)}” leva para ${href}, que não existe no site.`, el: a, fix: null});
      } catch { /* offline: nothing to say */ }
    }));
    return issues;
  }

  function showIssues(issues) {
    const list = $('div', {class: 'jarl-problemas'});
    let close;
    const draw = () => {
      list.replaceChildren(...issues.map(issue => $('div', {class: 'jarl-problema'},
        $('span', {}, issue.text),
        $('div', {class: 'jarl-problema-acoes'},
          $('button', {class: 'jarl-btn jarl-small', on: {click: () => {
            close(); issue.el.scrollIntoView({block: 'center', behavior: 'smooth'});
            const f = issue.el.closest('.jarl-ed'); if (f) activate(tokenOf.get(f));
          }}}, 'Ir até'),
          issue.fix ? $('button', {class: 'jarl-btn jarl-small', on: {click: () => {
            issue.fix.run(); issue.done = true;
            issues = issues.filter(i => !i.done); draw();
            if (!issues.length) { close(); toast('Tudo certo. Pode salvar.'); }
          }}}, issue.fix.label) : null))));
    };
    draw();
    close = showModal(`Antes de publicar: ${issues.length} ${issues.length === 1 ? 'ponto' : 'pontos'} para olhar`,
      [$('p', {}, 'Nada impede a publicação; são avisos. Corrija o que quiser e salve de novo.'), list],
      [{label: 'Publicar mesmo assim', primary: true, run: c => { c(); save({skipChecks: true}); }}]);
  }

  // ------------------------------------------------------------ section menu
  const sectionTitle = sec => squash((sec.querySelector('h1,h2,h3') || {}).textContent || sec.id);

  function addToMenu(sec) {
    // Copies the menu entry of the section right before this one (or the last
    // entry), points it here and gives it this section's title.
    const menu = menusOfPage()[0];
    if (!menu) { toast('Esta página não tem menu de seções.', 'erro'); return; }
    const entries = [...menu.querySelectorAll('a[href^="#"]')].filter(isField);
    if (!entries.length) { toast('O menu desta página não é editável.', 'erro'); return; }
    const order = [...document.querySelectorAll('[data-bloco]')].filter(el => LANDMARKS.has(el.tagName));
    let model = entries[entries.length - 1];
    for (const other of order.slice(0, order.indexOf(sec)).reverse()) {
      const hit = other.id && entries.find(a => a.getAttribute('href') === '#' + other.id);
      if (hit) { model = hit; break; }
    }
    const copy = duplicateBlock(model, {quiet: true});
    if (!copy) return;
    setBlockLink(copy, '#' + sec.id, false);
    setMenuLabel(copy, sectionTitle(sec));
    S.menuLinks.set(sec, copy);
    deactivate();
    toast(`“${sectionTitle(sec)}” entrou no menu.`);
  }

  function setMenuLabel(link, label) {
    // The label is the deepest text in the link (the home menu wraps it in a span).
    const walker = document.createTreeWalker(link, NodeFilter.SHOW_TEXT);
    let last = null, node;
    while ((node = walker.nextNode())) if (squash(node.data)) last = node;
    if (last) last.data = label; else link.textContent = label;
  }

  function syncMenuLabels() {
    // A section added and then renamed: its menu entry follows the new title.
    for (const [sec, link] of S.menuLinks) {
      if (document.contains(sec) && document.contains(link)) setMenuLabel(link, sectionTitle(sec));
    }
  }

  function offerMenu(sec) {
    if (!sec || !sec.id || !menusOfPage().length) return;
    S.newSections.add(sec);
    toast('Seção criada. Quer que ela apareça no menu da página?', 'ok',
          {label: 'Incluir no menu', run: () => addToMenu(sec)});
  }

  function signedOut() {
    document.cookie = `${HINT}=; Max-Age=0; path=/; secure; samesite=lax`;
    toast('Sua sessão do painel expirou. Entre de novo pelo Jarl.', 'erro');
  }

  // ------------------------------------------------------------ events
  document.addEventListener('click', e => {
    if (!S.editing || e.target.closest('[data-jarl-ui]')) return;
    if (!e.target.closest('.jarl-menu')) closeMenus();
    const el = e.target.closest('.jarl-ed');
    if (el) {
      // In edit mode a click edits: links don't navigate, buttons don't fire.
      e.preventDefault();
      e.stopPropagation();
      activate(tokenOf.get(el));
    } else if (S.active && !e.target.closest('.jarl-active')) {
      deactivate();
    } else if (e.target.closest('a,button')) {
      // Outside the editable text, links still don't leave the draft behind.
      if (pendingCount()) { e.preventDefault(); toast('Salve ou descarte antes de sair desta página.', 'erro'); }
    }
  }, true);

  document.addEventListener('contextmenu', contextMenu, true);
  document.addEventListener('selectionchange', rememberSelection);
  addEventListener('scroll', () => { if (!ui.menu.hidden) closeMenus(); }, {passive: true});
  addEventListener('resize', positionToolbar);

  function handleKey(e) {
    if (!S.editing) return false;
    const mod = e.ctrlKey || e.metaKey;
    const key = e.key.toLowerCase();
    if (mod && key === 'z' && !e.shiftKey) { e.preventDefault(); undo(); return; }
    if (mod && ((key === 'z' && e.shiftKey) || key === 'y')) { e.preventDefault(); redo(); return; }
    if (mod && key === 's') { e.preventDefault(); save(); return; }
    if (e.key === 'Escape') { closeMenus(); deactivate(); return; }
    if (!S.active) return;
    const el = target();
    const field = S.fields.get(S.active);
    if (mod && key === 'd') { e.preventDefault(); duplicateBlock(el); return; }
    if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault(); moveBlock(el, e.key === 'ArrowUp' ? 'cima' : 'baixo'); return;
    }
    if (!targetIsField() && (e.key === 'Delete' || e.key === 'Backspace')) {
      e.preventDefault(); removeBlock(el); return;
    }
    if (mod && key === 'k') {
      e.preventDefault();
      const btn = [...ui.toolbar.querySelectorAll('.jarl-tool')].find(b => b.textContent.startsWith('🔗'));
      if (btn) btn.click();
      return;
    }
    if (mod && ['b', 'i', 'u'].includes(key)) {
      e.preventDefault();
      if (!field.simples) toggleInline({b: 'bold', i: 'italic', u: 'underline'}[key]);
      return;
    }
    if (e.key === 'Enter' && targetIsField()) {
      e.preventDefault();
      if (!field.simples) document.execCommand('insertLineBreak');
    }
    return false;
  }
  document.addEventListener('keydown', e => {
    if (e.target.closest && e.target.closest('[data-jarl-ui]')) return;
    handleKey(e);
  }, true);

  document.addEventListener('paste', e => {
    if (!S.active || !S.elements.get(S.active).contains(e.target)) return;
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData('text/plain');
    document.execCommand('insertText', false, text);
  }, true);

  addEventListener('beforeunload', e => {
    if (S.editing && pendingCount() && !S.busy) { e.preventDefault(); e.returnValue = ''; }
  });

  // ------------------------------------------------------------ start
  async function start() {
    try {
      const d = await api('/api/site/eu');
      S.user = d.usuario;
    } catch (error) {
      if (error.expired) document.cookie = `${HINT}=; Max-Age=0; path=/; secure; samesite=lax`;
      return;
    }
    buildUi();
    const wanted = new URLSearchParams(location.search).get('jarl') === 'editar';
    if (wanted || sessionStorage.getItem(EDITING_KEY)) setEditing(true);
  }

  // Lets the panel's Site tab drive a page shown in its frame.
  window.jarlEditor = {
    scrollTo(anchor, token) {
      const found = (token && S.elements.get(token)) || (anchor && document.getElementById(anchor));
      if (found) found.scrollIntoView({block: 'start', behavior: 'smooth'});
    },
    pending: () => pendingCount(),
    insertMarker,
    values: () => S.values,
    // for the full-screen editor
    state, save, undo, redo, discardAll, handleKey, insertLive, insertAfterSelection,
    selectSection, catalog, liveValue, deactivate, makePreview,
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
