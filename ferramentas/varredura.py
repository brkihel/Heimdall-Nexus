#!/usr/bin/python3
"""Varre TODOS os mods instalados contra Hexium E Thunderstore.

Consulta as duas lojas para cada pacote: uma pode estar a frente da outra.
Versoes pre-lancamento (beta/rc/alpha) sao sinalizadas, nao propostas.
"""
import json, re, urllib.request, concurrent.futures, os
from pathlib import Path

BASE = Path(os.environ.get('HEIMDALL_DATA_DIR', str(Path(__file__).resolve().parent.parent / 'dados')))
hx = {p['full_name']: p for p in json.loads((BASE/'catalogs'/'hexium.json').read_text())}
LOCK = Path(os.environ.get('HEIMDALL_MODS_LOCK', str(BASE/'mods.lock.current.json')))
lock = json.loads(LOCK.read_text())
inst = lock['packages']

PRE = re.compile(r'(beta|alpha|rc|pre|dev)', re.I)

# a pasta do pacote nem sempre e igual ao nome na loja: o patcher e distribuido
# Installed folder name -> published package id, for packages whose folder differs.
ALIAS: dict[str, str] = {}
def na_loja(n): return ALIAS.get(n, n)
def chave(s): return tuple(int(x) for x in re.findall(r'\d+', s)[:4])

def thunderstore(nome):
    if '-' not in nome: return None
    ns, nm = nome.split('-', 1)
    url = f"https://thunderstore.io/api/experimental/package/{ns}/{nm}/"
    try:
        req = urllib.request.Request(url, headers={'User-Agent':'heimdall-modsync/1.0'})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        return d['latest']['version_number'], d['latest'].get('date_created','')[:16]
    except Exception:
        return None

# consultas ao Thunderstore em paralelo
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    ts = dict(zip(inst, ex.map(thunderstore, [na_loja(n) for n in inst])))

linhas = []
for nome, i in sorted(inst.items()):
    atual = i.get('version') or '?'
    cands = []
    p = hx.get(na_loja(nome))
    if p: cands.append(('hexium', p['versions'][0]['version_number'],
                        p['versions'][0].get('date_created','')[:16]))
    if ts.get(nome): cands.append(('thunderstore', ts[nome][0], ts[nome][1]))
    estaveis = [c for c in cands if not PRE.search(c[1])]
    melhor = max(estaveis, key=lambda c: chave(c[1]), default=None)
    prerel  = [c for c in cands if PRE.search(c[1]) and chave(c[1]) > chave(atual)]
    estado = 'igual'
    if melhor and chave(melhor[1]) > chave(atual): estado = 'ATUALIZAR'
    elif not cands: estado = 'sem loja'
    linhas.append({'nome':nome,'atual':atual,'estado':estado,
                   'melhor':melhor,'pre':prerel,'cands':cands})

up = [l for l in linhas if l['estado']=='ATUALIZAR']
pre = [l for l in linhas if l['pre']]
sem = [l for l in linhas if l['estado']=='sem loja']

print(f"=== PRECISAM ATUALIZAR: {len(up)} ===")
for l in up:
    o,v,d = l['melhor']
    print(f"  {l['nome']:44s} {l['atual']:>10s} -> {v:<10s} ({o}, {d})")
print(f"\n=== SO EM PRE-LANCAMENTO (nao vou instalar): {len(pre)} ===")
for l in pre:
    for o,v,d in l['pre']:
        print(f"  {l['nome']:44s} {l['atual']:>10s} .. {v:<14s} ({o}, {d})")
print(f"\n=== NAO ENCONTRADOS EM LOJA NENHUMA: {len(sem)} ===")
for l in sem: print(f"  {l['nome']:44s} {l['atual']}")
print(f"\n=== EM DIA: {len(linhas)-len(up)-len(sem)} de {len(linhas)}")
json.dump([{'nome':l['nome'],'de':l['atual'],'para':l['melhor'][1],'loja':l['melhor'][0]} for l in up],
          open(BASE/'pendentes.json','w'), indent=2)
