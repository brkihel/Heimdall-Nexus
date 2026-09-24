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
})();
