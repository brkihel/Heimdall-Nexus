/* Consent-filtered Armory and recent Rankings, backed by the public Sagas API. */
(() => {'use strict';
const $=id=>document.getElementById(id), mode=document.body.dataset.hall;
const node=(tag,text,className)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e};
let world='',requestId=0;
function worldPicker(data){const select=$('world');select.replaceChildren();for(const entry of data.worlds){const option=node('option',entry.name||'Mundo');option.value=entry.id;option.selected=entry.id===data.world;select.append(option)}select.disabled=data.worlds.length<2}
function renderArmory(data){const box=$('cards');box.replaceChildren();const players=data.players||[];
  for(const player of players){const card=node('article',undefined,'hall-card');card.append(node('span','Inventário compartilhado','eyebrow'),node('h2',player.name||'Viking'),node('p',player.online?'● Online agora':'Equipamento do último registro',player.online?'online':''));
    const items=node('ul');for(const item of player.gear||[]){const row=node('li');row.append(node('span',item.name||'Item'),node('small',(item.slot||'Equipamento')+' · Q'+(item.quality||1)));items.append(row)}
    if(!items.children.length)items.append(node('li','Nenhum equipamento compartilhado.'));card.append(items);box.append(card)}
  $('status').textContent='Nenhum perfil com equipamento compartilhado neste mundo.';$('status').hidden=players.length>0;box.hidden=!players.length;
}
function renderRankings(data){const box=$('cards');box.replaceChildren();const players=data.players||[],events=data.events||[];
  const rows=players.map(player=>({player,kill:events.filter(e=>e.actor===player.id&&e.kind==='kill'&&!e.boss).length,boss:events.filter(e=>e.actor===player.id&&e.kind==='kill'&&e.boss).length,discover:events.filter(e=>e.actor===player.id&&e.kind==='discover').length})).filter(row=>row.kill||row.boss||row.discover).sort((a,b)=>(b.boss*5+b.discover*2+b.kill)-(a.boss*5+a.discover*2+a.kill)||a.player.name.localeCompare(b.player.name,'pt-BR'));
  for(const [index,row] of rows.entries()){const card=node('article',undefined,'hall-card');const head=node('div',undefined,'rank');head.append(node('b',String(index+1)),node('h2',row.player.name||'Viking'));card.append(head,node('p','Entre os últimos '+events.length+' momentos públicos deste mundo.'));
    const list=node('ul');for(const [value,label] of [[row.boss,'Chefes derrotados'],[row.discover,'Descobertas'],[row.kill,'Outros abates']]){const line=node('li');line.append(node('span',label),node('strong',String(value),'score'));list.append(line)}card.append(list);box.append(card)}
  $('status').textContent='Ainda não há feitos compartilhados para este recorte. A classificação usa apenas os momentos recentes autorizados pelos jogadores.';$('status').hidden=rows.length>0;box.hidden=!rows.length;
}
async function load(){const id=++requestId;try{const response=await fetch('/api/sagas/v1/overview?limit=100'+(world?'&world='+encodeURIComponent(world):''),{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(id!==requestId)return;if(!data.available){$('status').textContent='Sagas ainda não está ativa neste servidor.';$('status').hidden=false;$('cards').hidden=true;return}world=data.world||'';worldPicker(data);if(mode==='armaria')renderArmory(data);else renderRankings(data)}catch(_){if(id!==requestId)return;$('status').textContent='Não foi possível atualizar os dados agora. Tente novamente em instantes.';$('status').hidden=false}}
$('world').addEventListener('change',event=>{world=event.target.value;load()});load();setInterval(load,30000);
})();
