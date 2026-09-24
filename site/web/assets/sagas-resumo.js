/* Show the last consented moments where the home page already presents Vikings. */
(() => {'use strict';
const host=document.getElementById('saga-lista');if(!host)return;
const node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e};
const labels={death:'caiu em batalha',kill:'derrotou',discover:'descobriu',drop:'encontrou',collect:'coletou',pickup:'recolheu'};
const when=seconds=>new Date(Number(seconds)*1000).toLocaleDateString('pt-BR');
let region=null;
const links=node('div');links.className='sagas-destinos';host.after(links);
for(const [label,url] of [['Abrir mapa','/mapa/'],['Ler histórias','/historias/'],['Ver armaria','/armaria/'],['Rankings','/rankings/']]){const link=node('a',label);link.href=url;links.append(link)}
async function load(){try{const response=await fetch('/api/sagas/v1/overview?limit=8',{cache:'no-store'});if(!response.ok)return;const data=await response.json();if(!data.available)return;
  const events=Array.isArray(data.events)?data.events:[],feats=events.filter(e=>e.kind==='discover'||e.kind==='kill'&&(e.boss||e.elite||e.stars>=3));
  const moments=events.filter(event=>!feats.includes(event));
  if(!region){region=node('div');region.className='sagas-resumo';host.after(region)}region.replaceChildren();
  for(const [title,items] of [['Momentos recentes',moments.slice(0,3)],['Feitos recentes',feats.slice(0,3)]]){
    if(!items.length)continue;const section=node('section');section.append(node('h3',title));const list=node('ol');for(const event of items){const item=node('li');const art=window.HeimdallBossArt?.forEvent(event);if(art)window.HeimdallBossArt.apply(item,art);item.append(node('strong',(event.name||'Viking')+' '+(labels[event.kind]||'registrou')+(event.target?' '+event.target:'')),node('small',(art?'Chefe derrotado · ':'')+when(event.occurred_at)));list.append(item)}section.append(list);region.append(section)}
  region.hidden=!region.children.length;
  region.after(links);
}catch(_){/* The rest of the home page remains useful if Sagas is unavailable. */}}
load();setInterval(load,30000);
})();
