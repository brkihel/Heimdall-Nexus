/* Known battle illustrations are selected only for a credited boss kill. */
(() => {
  'use strict';
  const ART = Object.freeze({
    eikthyr: {name:'Eikthyr', file:'eikthyr', side:'left', position:'60% center', banner:'60% 25%'},
    elder: {name:'O Ancião', file:'elder', side:'left', position:'64% center', banner:'64% 5%'},
    bonemass: {name:'Bonemass', file:'bonemass', side:'right', position:'38% center', banner:'38% 15%'},
    moder: {name:'Moder', file:'moder', side:'right', position:'40% center', banner:'40% 15%'},
    yagluth: {name:'Yagluth', file:'yagluth', side:'left', position:'64% center', banner:'64% 15%'},
    queen: {name:'A Rainha', file:'queen', side:'left', position:'61% center', banner:'61% 22%'},
    kall: {name:'Kall Fimbulbringer', file:'kall-fimbulbringer', side:'right', position:'42% center', banner:'42% 15%'}
  });
  const ALIASES = Object.freeze({
    eikthyr:'eikthyr', eikthyrnir:'eikthyr',
    elder:'elder', anciao:'elder', gdking:'elder',
    bonemass:'bonemass', 'massa ossea':'bonemass',
    moder:'moder', modder:'moder', dragonqueen:'moder',
    yagluth:'yagluth', goblinking:'yagluth',
    queen:'queen', rainha:'queen', seekerqueen:'queen',
    'kall fimbulbringer':'kall', kallfimbulbringer:'kall'
  });
  function identify(target) {
    if (typeof target !== 'string' || target.length > 120) return null;
    const key = target.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase()
      .replace(/^[\s$]*(?:enemy[_\s]+)?(?:the |o |a )?/,'').replace(/[^a-z0-9]+/g,' ').trim();
    return ART[ALIASES[key]] || null;
  }
  function forEvent(event) {
    if (!event || event.kind !== 'kill' || event.boss !== true && event.boss !== 1) return null;
    const art = identify(event.target);
    return art ? {...art, url:'/assets/boss-fights/'+art.file+'.webp'} : null;
  }
  function forStory(story) {
    const events = Array.isArray(story?.evidence) ? story.evidence : [];
    for (let index=events.length-1; index>=0; index--) {
      const art=forEvent(events[index]);
      if (art) return art;
    }
    return null;
  }
  function apply(element, art) {
    element.classList.toggle('boss-fight',Boolean(art));
    element.dataset.textSide = art?.side || '';
    element.style.removeProperty('--boss-image');
    element.style.removeProperty('--boss-position');
    element.style.removeProperty('--boss-banner-position');
    if (art) {
      element.style.setProperty('--boss-image',`url("${art.url}")`);
      element.style.setProperty('--boss-position',art.position);
      element.style.setProperty('--boss-banner-position',art.banner);
    }
  }
  window.HeimdallBossArt = Object.freeze({forEvent,forStory,apply});

  function decorateStories() {
    const host=document.getElementById('chapters');
    if (!host) return;
    let request=0;
    async function update() {
      const cards=[...host.querySelectorAll(':scope > .chapter')];
      if (!cards.length || host.hidden) return;
      const id=++request, world=document.getElementById('world')?.value||'';
      try {
        const response=await fetch('/api/sagas/v1/overview?limit=1&story_limit=20'+
          (world?'&world='+encodeURIComponent(world):''),{cache:'no-store'});
        if (!response.ok) return;
        const data=await response.json();
        const current=[...host.querySelectorAll(':scope > .chapter')];
        if (id!==request || data.world!==world || current.length!==data.stories?.length ||
            current.some((card,index)=>card.querySelector('h2')?.textContent!==data.stories[index].title)) return;
        current.forEach((card,index)=>{
          const art=forStory(data.stories[index]);
          apply(card,art);
          if (!art) return;
          if (!card.querySelector('.boss-art')) {
            const picture=document.createElement('div');picture.className='boss-art';
            picture.setAttribute('aria-hidden','true');card.prepend(picture);
          }
          if (!card.querySelector('.boss-label')) {
            const label=document.createElement('span');label.className='boss-label';
            label.textContent='Luta contra '+art.name;
            card.querySelector('summary .eyebrow')?.after(label);
          }
          const facts=card.querySelectorAll('.chapter-proof li');
          const evidence=Array.isArray(data.stories[index].evidence)?data.stories[index].evidence:[];
          if (facts.length===evidence.length) {
            evidence.forEach((fact,position)=>{
              if (forEvent(fact)) facts[position].textContent=(fact.name||'Viking')+
                ' derrotou '+fact.target+' · '+new Date(Number(fact.occurred_at)*1000)
                  .toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'});
            });
          }
        });
      } catch (_) { /* The chapters stay readable without illustration. */ }
    }
    new MutationObserver(records=>{
      if (records.some(record=>[...record.addedNodes,...record.removedNodes]
          .some(node=>node.nodeType===1 && node.classList.contains('chapter')))) update();
    }).observe(host,{childList:true});
    if (host.children.length) update();
  }

  function decorateMap() {
    const info=document.getElementById('atlas-info');
    if (!info) return;
    let request=0, cachedWorld='', cachedEvents=[], cachedAt=0;
    async function update() {
      const id=++request;
      if (info.hidden || document.getElementById('atlas-info-kind')?.textContent!=='Chefe derrotado') {
        apply(info,null);return;
      }
      const title=document.getElementById('atlas-info-title')?.textContent;
      const world=document.getElementById('world')?.value||'';
      try {
        if (world!==cachedWorld || Date.now()-cachedAt>30000) {
          const response=await fetch('/api/sagas/v1/overview?limit=100&world='+
            encodeURIComponent(world),{cache:'no-store'});
          if (!response.ok) return;
          const data=await response.json();
          cachedWorld=world;cachedEvents=Array.isArray(data.events)?data.events:[];cachedAt=Date.now();
        }
        if (id!==request || info.hidden || document.getElementById('atlas-info-title')?.textContent!==title) return;
        const event=cachedEvents.find(item=>item.kind==='kill' && item.boss &&
          (item.name||'Viking')+' derrotou'+(item.target?' '+item.target:'')===title);
        apply(info,forEvent(event));
      } catch (_) { apply(info,null); }
    }
    new MutationObserver(update).observe(info,{attributes:true,attributeFilter:['hidden'],
      childList:true,characterData:true,subtree:true});
  }
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>{
    decorateStories();decorateMap();
  },{once:true});
  else {decorateStories();decorateMap()}
})();
