/* One public menu on every page; the Jarl editor publishes the configuration. */
(() => {
  'use strict';
  const fallback = {style:'discreto',links:[
    {label:'Início',url:'/'},{label:'Wiki',url:'/wiki/'},
    {label:'Mapa',url:'/mapa/'},{label:'Histórias',url:'/historias/'},
    {label:'Armaria',url:'/armaria/'},{label:'Rankings',url:'/rankings/'}]};
  const start = async () => {
    let config = fallback;
    try {
      const response = await fetch('/assets/navegacao.json', {cache:'no-store'});
      if (response.ok) {
        const value = await response.json();
        if (Array.isArray(value.links) && value.links.length <= 50) config = value;
      }
    } catch (_) { /* The fallback keeps navigation usable during installation. */ }
    const nav = document.createElement('nav');
    nav.className = 'heimdall-nav';
    nav.setAttribute('aria-label','Navegação principal');
    nav.dataset.style = config.style === 'destaque' ? 'destaque' : 'discreto';
    if (config.style === 'personalizado' && config.palette &&
        ['background','text','accent'].every(key => /^#[0-9a-fA-F]{6}$/.test(config.palette[key]))) {
      nav.dataset.style = 'personalizado';
      for (const [key,property] of [['background','--nav-bg'],['text','--nav-text'],['accent','--nav-accent']])
        nav.style.setProperty(property,config.palette[key]);
    }
    const inner = document.createElement('div');inner.className = 'heimdall-nav-inner';
    const brand = document.createElement('a');brand.className = 'heimdall-nav-brand';brand.href = '/';
    const identity = document.querySelector('[data-identidade="nome"]');
    brand.textContent = identity?.getAttribute('content') || identity?.textContent?.trim() ||
      (typeof config.name === 'string' ? config.name.slice(0,60) : '') || 'Heimdall Nexus';
    const links = document.createElement('div');links.className = 'heimdall-nav-links';
    const editing = new URLSearchParams(location.search).get('jarl') === 'editar';
    const valid = entry => entry && typeof entry.label === 'string' &&
      typeof entry.url === 'string' && /^\/(?:[a-z0-9-]{1,40}\/){0,3}$/.test(entry.url);
    const anchor = entry => {
      const link = document.createElement('a');link.href = entry.url;
      link.textContent = entry.label.slice(0,28);
      if (location.pathname === entry.url) link.setAttribute('aria-current','page');
      if (editing) link.addEventListener('click', event => event.preventDefault());
      return link;
    };
    for (const [index,entry] of config.links.entries()) {
      if (!valid(entry)) continue;
      const item = document.createElement('div');item.className = 'heimdall-nav-item';
      const link = anchor(entry);link.className = 'heimdall-nav-link';item.append(link);
      const children = Array.isArray(entry.children) ? entry.children.filter(valid).slice(0,12) : [];
      if (children.length) {
        item.classList.add('has-children');
        const toggle = document.createElement('button');toggle.type = 'button';
        toggle.className = 'heimdall-nav-toggle';toggle.textContent = '⌄';
        toggle.setAttribute('aria-label', `Mostrar links de ${entry.label.slice(0,28)}`);
        toggle.setAttribute('aria-expanded', 'false');
        const submenu = document.createElement('div');submenu.className = 'heimdall-nav-submenu';
        submenu.id = `heimdall-submenu-${index}`;
        submenu.setAttribute('aria-label', `Páginas de ${entry.label.slice(0,28)}`);
        toggle.setAttribute('aria-controls', submenu.id);
        for (const child of children) submenu.append(anchor(child));
        if (children.some(child => location.pathname === child.url))
          item.classList.add('has-current-child');
        const setOpen = open => {
          if (open) links.querySelectorAll('.heimdall-nav-item.is-open').forEach(other => {
            if (other === item) return;
            other.classList.remove('is-open');
            other.querySelector('.heimdall-nav-toggle')?.setAttribute('aria-expanded','false');
          });
          item.classList.toggle('is-open',open);
          toggle.setAttribute('aria-expanded',String(open));
        };
        toggle.addEventListener('click', () => setOpen(!item.classList.contains('is-open')));
        link.addEventListener('focus', () => setOpen(true));
        item.addEventListener('focusout', () => setTimeout(() => {
          if (!item.contains(document.activeElement)) setOpen(false);
        }, 0));
        item.addEventListener('pointerenter', () => {
          if (matchMedia('(hover:hover)').matches) setOpen(true);
        });
        item.addEventListener('pointerleave', () => {
          if (!item.contains(document.activeElement)) setOpen(false);
        });
        item.append(toggle,submenu);
      }
      links.append(item);
    }
    inner.append(brand, links);nav.append(inner);document.body.prepend(nav);
    document.addEventListener('click', event => {
      if (nav.contains(event.target)) return;
      links.querySelectorAll('.heimdall-nav-item.is-open').forEach(item => {
        item.classList.remove('is-open');
        item.querySelector('.heimdall-nav-toggle')?.setAttribute('aria-expanded','false');
      });
    });
    nav.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      const open = links.querySelector('.heimdall-nav-item.is-open');
      if (!open) return;
      open.classList.remove('is-open');
      const toggle = open.querySelector('.heimdall-nav-toggle');
      toggle.setAttribute('aria-expanded','false');toggle.focus();
    });
    const height = () => document.documentElement.style.setProperty('--heimdall-nav-height',nav.offsetHeight+'px');
    height();
    if (window.ResizeObserver) new ResizeObserver(height).observe(nav);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
