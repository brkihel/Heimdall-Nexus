// Floating notices for every Jarl page (docs/PADROES-GENESISMODS.md).
// Success and info fade out on their own; errors stay until closed and show
// their HN-… code so a report pinpoints the failure at once.
(() => {
  'use strict';
  const CODE = /^(HN-[A-Z]{3,5}-\d{3}): ([\s\S]*)$/;
  let area = null;

  function region() {
    if (area) return area;
    area = document.createElement('div');
    area.className = 'avisos';
    area.setAttribute('aria-live', 'polite');
    document.body.append(area);
    return area;
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // navigator.clipboard needs HTTPS or localhost; a panel reached over plain
  // HTTP (a test VM by IP) falls back to a hidden textarea.
  function copiarTexto(texto) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(texto);
    return new Promise((ok, falha) => {
      const area = el('textarea');
      area.value = texto;
      area.setAttribute('readonly', '');
      area.style.cssText = 'position:fixed;top:-1000px;opacity:0';
      document.body.append(area);
      area.select();
      const feito = document.execCommand('copy');
      area.remove();
      feito ? ok() : falha(new Error('copy refused'));
    });
  }
  window.copiarTexto = copiarTexto;

  function fechar(box) {
    box.classList.add('saindo');
    setTimeout(() => box.remove(), 220);
  }

  // avisar({tipo: 'ok'|'erro'|'info'|'andamento', titulo, texto, codigo, solucao,
  //         detalhes, duracao}). 'andamento' stays until fecharAviso(box) and
  //         its text can change with atualizarAviso(box, texto).
  window.avisar = function avisar(opcoes) {
    const tipo = opcoes.tipo || 'info';
    let {codigo = '', texto = ''} = opcoes;
    const match = CODE.exec(texto);
    if (match && !codigo) [, codigo, texto] = match;
    const box = el('div', 'aviso-flutuante ' + tipo);
    box.setAttribute('role', tipo === 'erro' ? 'alert' : 'status');
    const icone = el('span', 'aviso-icone', tipo === 'erro' ? '!' : tipo === 'ok' ? '✓' : 'ᚺ');
    if (tipo === 'andamento') { icone.classList.add('girando-aviso'); icone.textContent = ''; }
    icone.setAttribute('aria-hidden', 'true');
    const corpo = el('div', 'aviso-corpo');
    if (codigo) corpo.append(el('span', 'aviso-codigo', codigo));
    corpo.append(el('strong', '', opcoes.titulo || (tipo === 'erro' ? 'Algo deu errado' : 'Pronto')));
    if (texto) corpo.append(el('p', '', texto));
    if (opcoes.solucao) corpo.append(el('p', 'aviso-solucao', 'Como resolver: ' + opcoes.solucao));
    if (opcoes.detalhes) {
      const bloco = el('details', 'aviso-detalhes');
      bloco.append(el('summary', '', 'Ver registro técnico'), el('pre', '', opcoes.detalhes));
      corpo.append(bloco);
    }
    box.append(icone, corpo);
    if (tipo === 'andamento') {
      region().append(box);
      return box;
    }
    const persistente = tipo === 'erro' || opcoes.duracao === 0;
    if (persistente) {
      const acoes = el('div', 'aviso-acoes');
      if (opcoes.detalhes) {
        const relatorio = el('button', 'btn mini', 'Copiar relatório');
        relatorio.type = 'button';
        relatorio.addEventListener('click', () => copiarTexto([
          codigo, opcoes.titulo, texto, opcoes.solucao && 'Como resolver: ' + opcoes.solucao,
          new Date().toISOString(), '', opcoes.detalhes].filter(x => x !== undefined && x !== null && x !== false).join('\n'))
          .then(() => { relatorio.textContent = 'Copiado'; }, () => {}));
        acoes.append(relatorio);
      } else if (codigo) {
        const copiar = el('button', 'btn mini', 'Copiar código');
        copiar.type = 'button';
        copiar.addEventListener('click', () => copiarTexto(
          codigo + ' ' + (opcoes.titulo || '') + (texto ? ' — ' + texto : ''))
          .then(() => { copiar.textContent = 'Copiado'; }, () => {}));
        acoes.append(copiar);
      }
      const x = el('button', 'aviso-fechar', '×');
      x.type = 'button';
      x.setAttribute('aria-label', 'Fechar aviso');
      x.addEventListener('click', () => fechar(box));
      box.append(x);
      if (acoes.children.length) corpo.append(acoes);
    } else {
      const duracao = opcoes.duracao || 6000;
      const barra = el('i', 'aviso-tempo');
      barra.style.animationDuration = duracao + 'ms';
      box.append(barra);
      setTimeout(() => fechar(box), duracao);
    }
    region().append(box);
    return box;
  };
  window.atualizarAviso = (box, texto) => {
    const p = box && box.querySelector('.aviso-corpo p');
    if (p) p.textContent = texto;
  };
  window.fecharAviso = box => { if (box && box.isConnected) fechar(box); };

  // In-page confirmation. The browser's confirm() can be silenced by the user
  // ("prevent this page from creating dialogs"), and then answers "no" without
  // showing anything: every guarded button looks dead. Resolves true or false.
  const ESTILO = `
.confirma{max-width:min(460px,calc(100vw - 32px));padding:0;border:1px solid var(--borda-viva,#33475a);border-radius:3px;
  background:linear-gradient(168deg,#152029,#080e14);color:var(--texto,#b4bec7);box-shadow:0 24px 60px rgba(0,0,0,.6);
  font:15px/1.5 Spectral,Georgia,serif}
.confirma::backdrop{background:rgba(3,6,9,.72);backdrop-filter:blur(2px)}
.confirma.perigo{border-color:#9b5944}
.confirma-corpo{padding:1.3rem 1.4rem 1rem}
.confirma h2{margin:0 0 .6rem;font:600 .95rem Cinzel,Georgia,serif;letter-spacing:.08em;text-transform:uppercase;color:var(--osso,#e6e0d2)}
.confirma.perigo h2{color:#e0664f}
.confirma p{margin:0 0 .5rem;white-space:pre-line}
.confirma-acoes{display:flex;justify-content:flex-end;gap:.6rem;padding:.8rem 1.4rem 1.2rem}
.confirma-acoes button{min-height:40px;padding:.5rem 1.1rem;border-radius:3px;cursor:pointer;font:600 .72rem Cinzel,Georgia,serif;
  letter-spacing:.12em;text-transform:uppercase;border:1px solid var(--borda-viva,#33475a);background:transparent;color:var(--osso,#e6e0d2)}
.confirma-acoes .sim{background:linear-gradient(180deg,#d8b66c,#b08c45);border-color:#c8a45c;color:#1a1206}
.confirma.perigo .confirma-acoes .sim{background:#7a2e22;border-color:#c0392b;color:#fbe9e5}
.confirma-acoes button:focus-visible{outline:2px solid var(--ouro-claro,#eeddb0);outline-offset:2px}`;
  let estilo = false;
  window.confirmar = function confirmar(texto, opcoes = {}) {
    if (!estilo) {
      const tag = el('style'); tag.textContent = ESTILO; document.head.append(tag); estilo = true;
    }
    return new Promise(resolve => {
      const caixa = el('dialog', 'confirma' + (opcoes.perigo ? ' perigo' : ''));
      caixa.setAttribute('aria-modal', 'true');
      const corpo = el('div', 'confirma-corpo');
      corpo.append(el('h2', null, opcoes.titulo || 'Confirmar'));
      for (const parte of String(texto).split(/\n{2,}/)) corpo.append(el('p', null, parte));
      const acoes = el('div', 'confirma-acoes');
      const nao = el('button', 'nao', opcoes.cancelar || 'Cancelar');
      const sim = el('button', 'sim', opcoes.acao || 'Confirmar');
      nao.type = sim.type = 'button';
      acoes.append(nao, sim);
      caixa.append(corpo, acoes);
      let resposta = false;
      nao.addEventListener('click', () => caixa.close());
      sim.addEventListener('click', () => { resposta = true; caixa.close(); });
      caixa.addEventListener('close', () => { caixa.remove(); resolve(resposta); });
      document.body.append(caixa);
      caixa.showModal();
      // A risky action starts on "Cancelar": Enter alone never destroys anything.
      (opcoes.perigo ? nao : sim).focus();
    });
  };
})();
