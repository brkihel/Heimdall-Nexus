/* Consent-filtered Armory (Viking profiles) and recent Rankings, backed by the public Sagas API. */
(() => {'use strict';
const $=id=>document.getElementById(id), mode=document.body.dataset.hall;
const node=(tag,text,className)=>{const e=document.createElement(tag);if(text!==undefined&&text!==null)e.textContent=text;if(className)e.className=className;return e};
let world='',requestId=0;

// ------------------------------------------------------------------ rankings
function renderRankings(data){const box=$('cards');box.replaceChildren();const players=data.players||[],events=data.events||[];
  const rows=players.map(player=>({player,kill:events.filter(e=>e.actor===player.id&&e.kind==='kill'&&!e.boss).length,boss:events.filter(e=>e.actor===player.id&&e.kind==='kill'&&e.boss).length,discover:events.filter(e=>e.actor===player.id&&e.kind==='discover').length})).filter(row=>row.kill||row.boss||row.discover).sort((a,b)=>(b.boss*5+b.discover*2+b.kill)-(a.boss*5+a.discover*2+a.kill)||a.player.name.localeCompare(b.player.name,'pt-BR'));
  for(const [index,row] of rows.entries()){const card=node('article',undefined,'hall-card');const head=node('div',undefined,'rank');head.append(node('b',String(index+1)),node('h2',row.player.name||'Viking'));card.append(head,node('p','Entre os últimos '+events.length+' momentos públicos deste mundo.'));
    const list=node('ul');for(const [value,label] of [[row.boss,'Chefes derrotados'],[row.discover,'Descobertas'],[row.kill,'Outros abates']]){const line=node('li');line.append(node('span',label),node('strong',String(value),'score'));list.append(line)}card.append(list);box.append(card)}
  $('status').textContent='Ainda não há feitos compartilhados para este recorte. A classificação usa apenas os momentos recentes autorizados pelos jogadores.';$('status').hidden=rows.length>0;box.hidden=!rows.length;
}

// ------------------------------------------------------------------ armory
// Where each piece sits around the portrait; names follow the game's item types.
const LEFT=[['Helmet','Capacete'],['Chest','Peito'],['Legs','Pernas'],['Hands','Mãos']];
const RIGHT=[['Shoulder','Capa'],['Utility','Utilitário'],['Trinket','Bugiganga'],['Ring','Anel'],['Necklace','Colar']];
const WEAPONS=new Set(['OneHandedWeapon','TwoHandedWeapon','TwoHandedWeaponLeft','Bow','Torch','Tool']);
const TYPE={Helmet:'Capacete',Chest:'Peito',Legs:'Pernas',Hands:'Mãos',Shoulder:'Capa',Utility:'Utilitário',Trinket:'Bugiganga',Ring:'Anel',Necklace:'Colar',
  OneHandedWeapon:'Arma de uma mão',TwoHandedWeapon:'Arma de duas mãos',TwoHandedWeaponLeft:'Arma de duas mãos',Bow:'Arco',Torch:'Tocha',Tool:'Ferramenta',
  Shield:'Escudo',Ammo:'Munição',AmmoNonEquipable:'Munição',Consumable:'Consumível',Material:'Material',Trophy:'Troféu',Fish:'Peixe',Misc:'Diverso',Attach_Atgeir:'Atgeir'};
const DAMAGE={damage:'Dano',blunt:'contundente',slash:'cortante',pierce:'perfurante',chop:'de corte (árvores)',pickaxe:'de mineração',fire:'de fogo',frost:'de gelo',lightning:'de raio',poison:'de veneno',spirit:'espiritual'};
const ELEMENT={Blunt:'Contundente',Slash:'Cortante',Pierce:'Perfurante',Chop:'Corte (árvores)',Pickaxe:'Mineração',Fire:'Fogo',Frost:'Gelo',Lightning:'Raio',Poison:'Veneno',Spirit:'Espiritual'};
const MODIFIER={Normal:'normal',Resistant:'resistente',Weak:'fraco',Immune:'imune',Ignore:'ignora',VeryResistant:'muito resistente',VeryWeak:'muito fraco',SlightlyResistant:'levemente resistente',SlightlyWeak:'levemente fraco'};
const VITALS={Health:'Vida',Stamina:'Vigor',Eitr:'Eitr',Armor:'Armadura'};
const state={players:[],selected:new URLSearchParams(location.search).get('viking')||'',viking:null,tab:'personagem',search:''};

const fmt=value=>Number(value).toLocaleString('pt-BR',{maximumFractionDigits:1});
const when=seconds=>new Date(seconds*1000).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
const mediaUrl=(player,id)=>`/api/sagas/v1/vikings/${encodeURIComponent(player.id)}/media/${encodeURIComponent(id)}.png`;
function statLabel(name){if(VITALS[name])return VITALS[name];if(name==='Block')return 'Bloqueio';if(name==='Movement')return 'Movimento';
  const damage=/^Damage (\w+)$/.exec(name);if(damage){const key=damage[1].toLowerCase();return key==='damage'?'Dano':'Dano '+(DAMAGE[key]||key)}return name}
function statValue(name,value){return name==='Movement'?(value>0?'+':'')+fmt(value*100)+'%':fmt(value)}
function effectLabel(text){const set=/^Set (\d+): (.*)$/.exec(text);if(set)return `Conjunto de ${set[1]} peças: ${set[2]}`;
  const mod=/^(\w+): (\w+)$/.exec(text);if(mod&&ELEMENT[mod[1]])return `${ELEMENT[mod[1]]}: ${MODIFIER[mod[2]]||mod[2]}`;return text}

function icon(player,id,alt){const box=node('span',undefined,'vp-icon');if(id){const img=node('img');img.alt=alt||'';img.loading='lazy';img.decoding='async';img.src=mediaUrl(player,id);
  img.onerror=()=>img.remove();box.append(img)}return box}

// Details of one item, shown beside it on hover, focus or tap.
const tip=node('div',undefined,'vp-tip');tip.setAttribute('role','tooltip');tip.hidden=true;tip.id='vp-tip';
function showTip(player,item,anchor){tip.replaceChildren();tip.append(node('strong',item.name||'Item'));
  tip.append(node('small',[TYPE[item.type||item.slot]||item.type||item.slot,'Qualidade '+(item.quality||1),item.active?'em uso':''].filter(Boolean).join(' · ')));
  if(item.max_durability>0){const bar=node('div',undefined,'vp-durability');const fill=node('i');fill.style.width=Math.max(0,Math.min(100,item.durability/item.max_durability*100))+'%';
    bar.append(fill);tip.append(node('span','Durabilidade '+fmt(item.durability)+' / '+fmt(item.max_durability),'vp-tip-label'),bar)}
  if((item.stats||[]).length){const list=node('dl');for(const stat of item.stats){list.append(node('dt',statLabel(stat.name)),node('dd',statValue(stat.name,stat.value)))}tip.append(list)}
  if((item.effects||[]).length){const list=node('ul');for(const effect of item.effects)list.append(node('li',effectLabel(effect)));tip.append(list)}
  if((item.sockets||[]).length){const box=node('div',undefined,'vp-sockets');box.append(node('span','Engastes','vp-tip-label'));
    for(const socket of item.sockets){const row=node('div',undefined,'vp-socket');row.append(icon(player,socket.icon,''),node('b',socket.name||'Engaste vazio'));
      if((socket.effects||[]).length)row.append(node('small',socket.effects.join(' · ')));box.append(row)}tip.append(box)}
  document.body.append(tip);tip.hidden=false;const r=anchor.getBoundingClientRect(),t=tip.getBoundingClientRect();
  let x=r.right+10;if(x+t.width>innerWidth-8)x=Math.max(8,r.left-t.width-10);const y=Math.min(innerHeight-t.height-8,Math.max(8,r.top));
  tip.style.left=x+'px';tip.style.top=y+'px';anchor.setAttribute('aria-describedby','vp-tip')}
function hideTip(){tip.hidden=true}
function describable(el,player,item){el.tabIndex=0;el.addEventListener('pointerenter',()=>showTip(player,item,el));el.addEventListener('pointerleave',hideTip);
  el.addEventListener('focus',()=>showTip(player,item,el));el.addEventListener('blur',hideTip);
  el.addEventListener('click',()=>tip.hidden?showTip(player,item,el):hideTip())}

function gearCard(player,item,label){const card=node('div',undefined,'vp-card'+(item?'':' vp-empty'));
  if(!item){const text=node('div');text.append(node('b',label),node('small','vazio'));card.append(node('span',undefined,'vp-icon'),text);return card}
  if(item.socket_color)card.style.setProperty('--accent',item.socket_color);
  const text=node('div');text.append(node('b',item.name||label),node('small',label+' · Q'+(item.quality||1)),node('small',item.active?'Em uso':'Equipado','vp-state'));
  card.append(icon(player,item.icon,''),text);describable(card,player,item);return card}

function column(player,gear,slots,extra){const col=node('div',undefined,'vp-col');
  for(const [slot,label] of slots){const items=gear.filter(g=>(g.slot||g.type)===slot);
    if(items.length)for(const item of items)col.append(gearCard(player,item,label));
    else if(['Helmet','Chest','Legs','Shoulder'].includes(slot))col.append(gearCard(player,null,label))}
  if(extra.length){col.append(node('div',undefined,'vp-gap'));for(const [item,label] of extra)col.append(gearCard(player,item,label))}
  return col}

function renderPicker(){const box=$('vp-picker');box.replaceChildren();const q=state.search.trim().toLocaleLowerCase('pt-BR');
  const list=state.players.filter(p=>!q||(p.name||'').toLocaleLowerCase('pt-BR').includes(q));
  for(const player of list){const button=node('button',undefined,'vp-chip');button.type='button';button.setAttribute('aria-pressed',String(player.id===state.selected));
    button.append(node('span',undefined,player.online?'vp-dot on':'vp-dot'),node('span',player.name||'Viking'));
    button.addEventListener('click',()=>select(player.id));box.append(button)}
  if(!list.length)box.append(node('small',q?'Nenhum Viking com esse nome.':'Nenhum Viking compartilhou o perfil ainda.','vp-none'))}

// The round avatar zooms on the head. Poses differ (raised weapons, capes), so
// the head is found in each portrait: the first opaque rows near the middle.
function headshot(avatar,url){const art=new Image();art.onload=()=>{
  const w=64,h=96,canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;const ctx=canvas.getContext('2d');
  let x=.5,y=.15;
  try{ctx.drawImage(art,0,0,w,h);const alpha=ctx.getImageData(0,0,w,h).data;const opaque=(cx,cy)=>alpha[(cy*w+cx)*4+3]>64;
    let top=-1;for(let cy=0;cy<h&&top<0;cy++){let count=0;for(let cx=Math.floor(w*.3);cx<w*.7;cx++)if(opaque(cx,cy))count++;if(count>=2)top=cy}
    if(top>=0){let sum=0,n=0;for(let cy=top;cy<Math.min(h,top+h*.1);cy++)for(let cx=0;cx<w;cx++)if(opaque(cx,cy)){sum+=cx;n++}
      if(n)x=sum/n/w;y=Math.min(.6,top/h+.075)}}catch(_){/* keep the default framing */}
  const size=avatar.clientWidth||72,width=size*3,height=width*1.5;
  avatar.style.backgroundImage=`url("${url}")`;avatar.style.backgroundColor="var(--ardosia)";avatar.style.backgroundSize=`${width}px ${height}px`;
  avatar.style.backgroundPosition=`${Math.round(size/2-x*width)}px ${Math.round(size/2-y*height)}px`;avatar.classList.add('has-portrait')};
  art.src=url}

function renderProfile(){const player=state.viking,box=$('vp-profile');box.replaceChildren();hideTip();if(!player){box.hidden=true;return}box.hidden=false;
  const head=node('header',undefined,'vp-head');const avatar=node('span',undefined,'vp-avatar');
  if(player.portrait)headshot(avatar,mediaUrl(player,player.portrait));else avatar.append(node('span','ᚹ'));
  const title=node('div');title.append(node('h2',player.name||'Viking'));const status=node('p',undefined,'vp-status');
  status.append(node('span',player.online?'● Online agora':'○ Offline',player.online?'vp-pill on':'vp-pill'),node('span',player.online?'':'Visto por último '+when(player.seen_at)));
  title.append(status);const vitals=node('div',undefined,'vp-vitals');for(const v of player.vitals||[])if(v.value>0){const item=node('span');item.append(node('b',fmt(v.value)),node('small',VITALS[v.name]||v.name));vitals.append(item)}
  head.append(avatar,title,vitals);
  const tabs=node('div',undefined,'vp-tabs');tabs.setAttribute('role','tablist');
  for(const [key,label] of [['personagem','Personagem'],['saga','Saga']]){const b=node('button',label);b.type='button';b.setAttribute('role','tab');b.setAttribute('aria-selected',String(state.tab===key));
    b.addEventListener('click',()=>{state.tab=key;renderProfile()});tabs.append(b)}
  setBackdrop(player);
  box.append(head,tabs,state.tab==='saga'?sagaPane(player):characterPane(player))}

// The page backdrop follows the biome of the Viking's latest shared feat when the
// site has art for it (/assets/armaria-<biome>.webp); otherwise the default stays.
const BIOMES={Meadows:'prados',BlackForest:'floresta-negra',Swamp:'pantano',Mountain:'montanha',Plains:'planicies',
  Mistlands:'terras-nebulosas',AshLands:'terras-de-cinzas',DeepNorth:'extremo-norte',Ocean:'oceano'};
let backdrop='';
function setBackdrop(player){const last=(player.events||[]).find(e=>BIOMES[e.biome]);const file=last?`/assets/armaria-${BIOMES[last.biome]}.webp`:'';
  if(file===backdrop)return;backdrop=file;const body=document.body;if(!file){body.style.removeProperty('--armaria-bg');return}
  const art=new Image();art.onload=()=>{if(backdrop===file)body.style.setProperty('--armaria-bg',`url("${file}")`)};
  art.onerror=()=>{if(backdrop===file)body.style.removeProperty('--armaria-bg')};art.src=file}

function characterPane(player){const gear=player.gear||[];
  const stage=node('section',undefined,'vp-stage');
  const notes=node('div',undefined,'vp-notes');notes.append(node('span','Último registro · '+when(player.seen_at)));stage.append(notes);
  const hands=gear.filter(g=>WEAPONS.has(g.slot||g.type)),shields=gear.filter(g=>(g.slot||g.type)==='Shield'),ammo=gear.filter(g=>(g.slot||g.type)==='Ammo');
  const left=column(player,gear,LEFT,hands.map(g=>[g,TYPE[g.slot||g.type]||'Arma']));
  const right=column(player,gear,RIGHT,[...shields.map(g=>[g,'Escudo']),...ammo.map(g=>[g,'Munição'])]);
  const figure=node('figure',undefined,'vp-portrait');
  if(player.portrait){const img=node('img');img.alt=`${player.name} com o equipamento atual`;img.src=mediaUrl(player,player.portrait);
    img.onerror=()=>{img.remove();figure.append(portraitMissing())};figure.append(img)}else figure.append(portraitMissing());
  stage.append(left,figure,right);
  const bar=node('div',undefined,'vp-hotbar');const title=node('div',undefined,'vp-hotbar-title');title.append(node('span','Barra rápida'),node('small','Posições 1–8'));
  const slots=node('div',undefined,'vp-slots');const byPos=new Map((player.hotbar||[]).map(item=>[item.hotbar,item]));
  for(let i=1;i<=8;i++){const item=byPos.get(i),slot=node('div',undefined,'vp-slot'+(item&&item.active?' active':'')+(item?'':' vp-empty'));slot.append(node('span',String(i),'vp-n'));
    if(item){slot.append(icon(player,item.icon,''),node('small',item.name||'Item'));if(item.active)slot.append(node('em','Em uso'));describable(slot,player,item)}slots.append(slot)}
  bar.append(title,slots);stage.append(bar,node('p','Passe o mouse, foque ou toque num item para ver os detalhes.','vp-hint'));return stage}

function portraitMissing(){const box=node('div',undefined,'vp-portrait-missing');
  box.innerHTML='<svg viewBox="0 0 120 200" aria-hidden="true"><path d="M60 14c14 0 24 11 24 26 0 9-4 17-10 22l18 9c9 5 14 14 14 24v42H94l-4 57H30l-4-57H14V95c0-10 5-19 14-24l18-9c-6-5-10-13-10-22 0-15 10-26 24-26Z"/></svg>';
  box.append(node('small','O retrato aparece quando o Viking usar o Heimdall Sagas Client 0.2 com o perfil compartilhado.'));return box}

function sagaPane(player){const pane=node('section',undefined,'vp-saga');const feats=player.feats||{};
  const grid=node('div',undefined,'vp-feats');for(const [key,label] of [['kills','Criaturas abatidas'],['bosses','Chefes derrotados'],['deaths','Mortes'],['discoveries','Descobertas']]){
    const card=node('article');card.append(node('span',label),node('strong',fmt(feats[key]||0)));grid.append(card)}
  pane.append(grid);const list=node('ol',undefined,'vp-events');
  for(const e of player.events||[]){const row=node('li');const text=e.kind==='death'?'Tombou em combate':e.kind==='discover'?'Descobriu '+(e.target||'um lugar'):
      (e.boss?'Derrotou o chefe ':'Abateu ')+(e.target||'uma criatura')+(e.stars?' '+'★'.repeat(Math.min(5,e.stars)):'');
    row.append(node('span',e.kind==='death'?'†':e.boss?'♜':e.kind==='discover'?'✦':'⚔','vp-glyph'),node('span',text),node('time',when(e.occurred_at)));list.append(row)}
  if(!list.children.length)pane.append(node('p','Ainda não há feitos compartilhados deste Viking.','vp-none'));else pane.append(list);
  const link=node('a','Ler as histórias do servidor','vp-link');link.href='/historias/';pane.append(link);return pane}

function select(id){if(id===state.selected&&state.viking)return;state.selected=id;state.tab='personagem';
  const url=new URL(location.href);url.searchParams.set('viking',id);history.replaceState(null,'',url);renderPicker();loadViking()}

let vikingRequest=0;
async function loadViking(){const id=++vikingRequest,actor=state.selected;if(!actor){state.viking=null;renderProfile();return}
  try{const response=await fetch('/api/sagas/v1/vikings/'+encodeURIComponent(actor),{cache:'no-store'});if(id!==vikingRequest)return;
    state.viking=response.ok?await response.json():null}catch(_){if(id!==vikingRequest)return}
  renderProfile()}

function buildArmory(){if($('vp-root'))return;const main=document.querySelector('main')||document.body;
  for(const old of main.querySelectorAll('.hall-controls'))old.hidden=true;$('cards').hidden=true;
  const root=node('section',undefined,'vp');root.id='vp-root';root.hidden=true;
  const finder=node('div',undefined,'vp-finder');const label=node('label','Encontrar um Viking');const input=node('input');input.type='search';input.placeholder='Nome do Viking';
  input.addEventListener('input',()=>{state.search=input.value;renderPicker()});label.append(input);const picker=node('div',undefined,'vp-picker');picker.id='vp-picker';
  finder.append(label,picker);const profile=node('article',undefined,'vp-profile');profile.id='vp-profile';root.append(finder,profile);
  $('status').after(root);addEventListener('scroll',hideTip,{passive:true})}

function renderArmory(data){buildArmory();const players=(data.players||[]).slice().sort((a,b)=>(b.online-a.online)||(b.seen_at-a.seen_at));state.players=players;
  $('vp-root').hidden=!players.length;$('status').textContent='Nenhum Viking compartilhou o perfil neste mundo ainda. O perfil aparece quando o jogador liga ShareProfile no Heimdall Sagas Client.';$('status').hidden=players.length>0;
  // Never an empty page: open the requested Viking, or whoever is online or was seen last.
  if(!players.some(p=>p.id===state.selected))state.selected=players[0]?players[0].id:'';
  renderPicker();loadViking()}

async function load(){const id=++requestId;try{const response=await fetch('/api/sagas/v1/overview?limit=100'+(world?'&world='+encodeURIComponent(world):''),{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(id!==requestId)return;if(!data.available){$('status').textContent='Sagas ainda não está ativa neste servidor.';$('status').hidden=false;$('cards').hidden=true;return}world=data.world||'';if(mode==='armaria')renderArmory(data);else renderRankings(data)}catch(_){if(id!==requestId)return;$('status').textContent='Não foi possível atualizar os dados agora. Tente novamente em instantes.';$('status').hidden=false}}
load();setInterval(load,30000);
})();
