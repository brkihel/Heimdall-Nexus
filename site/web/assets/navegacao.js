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
    for (const entry of config.links) {
      if (!entry || typeof entry.label !== 'string' || typeof entry.url !== 'string' ||
          !/^\/(?:[a-z0-9-]{1,40}\/){0,3}$/.test(entry.url)) continue;
      const link = document.createElement('a');link.href = entry.url;link.textContent = entry.label.slice(0,28);
      if (location.pathname === entry.url) link.setAttribute('aria-current','page');
      if (new URLSearchParams(location.search).get('jarl') === 'editar')
        link.addEventListener('click', event => event.preventDefault());
      links.append(link);
    }
    inner.append(brand, links);nav.append(inner);document.body.prepend(nav);
    const height = () => document.documentElement.style.setProperty('--heimdall-nav-height',nav.offsetHeight+'px');
    height();
    if (window.ResizeObserver) new ResizeObserver(height).observe(nav);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
