/* Render the modpack directory from its portable JSON feed. */
(function () {
  'use strict';
  var list = document.querySelector('.modlista');
  if (!list) return;

  function node(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text != null) el.textContent = text;
    return el;
  }
  function render(data) {
    if (!data || !Array.isArray(data.mods)) return;
    var fragment = document.createDocumentFragment();
    data.mods.forEach(function (mod) {
      var row = node('a', 'modlinha');
      row.setAttribute('role', 'listitem');
      if (/^https:\/\//i.test(mod.url || '')) {
        row.href = mod.url;
        row.target = '_blank';
        row.rel = 'noopener';
      } else {
        row.removeAttribute('href');
        row.setAttribute('aria-disabled', 'true');
      }
      row.dataset.modPacote = mod.pacote || '';
      var image = node('img', 'modcapa');
      image.alt = '';
      image.loading = 'lazy';
      image.decoding = 'async';
      image.width = 48;
      image.height = 48;
      var localCover = /^\/(?!\/)/.test(mod.capa || '');
      var remoteIcon = /^https:\/\//i.test(mod.icone || '');
      image.src = localCover ? mod.capa : remoteIcon ? mod.icone : '/assets/mod-placeholder.svg';
      image.onerror = function () {
        if (remoteIcon && image.src !== mod.icone) { image.src = mod.icone; return; }
        image.hidden = true;
      };
      row.appendChild(image);
      var copy = node('span', 'modtxt');
      var title = node('span', 'modnome', mod.nome || mod.pacote || 'Mod');
      title.appendChild(node('small', '', 'por ' + (mod.autor || 'autor desconhecido')));
      copy.appendChild(title);
      var description = node('span', 'moddesc', mod.descricao || 'Descrição ainda não cadastrada.');
      description.dataset.mod = mod.pacote || '';
      copy.appendChild(description);
      row.appendChild(copy);
      row.appendChild(node('span', 'modver', mod.versao || ''));
      fragment.appendChild(row);
    });
    list.replaceChildren(fragment);
    var count = document.querySelector('[data-modpack-count]');
    if (count) count.textContent = String(data.total || data.mods.length);
    var ownerCount = data.mods.filter(function (mod) { return mod.autor === data.modpack_owner; }).length;
    var ownerTotal = document.querySelector('[data-modpack-owned-count]');
    if (ownerTotal) ownerTotal.textContent = String(ownerCount);
    var version = document.querySelector('[data-modpack-version]');
    if (version) version.textContent = data.versao_pack || '—';
    document.querySelectorAll('[data-modpack-link]').forEach(function (link) {
      if (/^https:\/\//i.test(data.modpack || '')) {
        link.href = data.modpack;
        link.removeAttribute('aria-disabled');
      } else {
        link.removeAttribute('href');
        link.setAttribute('aria-disabled', 'true');
        link.title = 'Este servidor ainda não configurou um modpack.';
      }
    });
    document.dispatchEvent(new CustomEvent('heimdall:mods-rendered'));
  }

  fetch('/mods.json', {cache: 'no-store'}).then(function (response) {
    if (!response.ok) throw new Error('mods.json não está disponível');
    return response.json();
  }).then(render).catch(function (error) {
    console.warn('Lista de mods: mantendo a cópia de segurança embutida na página.', error);
  });
}());
