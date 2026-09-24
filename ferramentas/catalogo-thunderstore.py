#!/usr/bin/python3
"""Baixa o catálogo da Thunderstore (comunidade Valheim) e grava uma versão enxuta.

O catálogo cru tem uns 170 MB de JSON e custa perto de 1 GB de RAM para ler.
Por isso roda aqui, num processo que morre ao terminar, e não dentro do
executor: ele só lê o resultado, que fica com poucos MB. Do pacote guarda o que
o painel mostra; das versões antigas guarda só o número, porque o endereço de
download da Thunderstore sai do nome e da versão.

Sai com código 0 e imprime o total de pacotes; qualquer outro código é falha, e
o catálogo anterior fica como estava.
"""
import gzip
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(os.environ.get('HEIMDALL_DATA_DIR', str(Path(__file__).resolve().parent.parent / 'dados')))
DESTINO = BASE / 'catalogs' / 'thunderstore.json'
API = 'https://thunderstore.io/c/valheim/api/v1/package/'
API_PACOTE = 'https://thunderstore.io/api/experimental/package/{dono}/{nome}/'
LOCK = Path(os.environ.get('HEIMDALL_MODS_LOCK', '/srv/valheim/current/mods.lock.json'))
CAMPOS = ('name', 'full_name', 'owner', 'package_url', 'date_updated',
          'rating_score', 'is_deprecated', 'categories')


def enxuga(pacote: dict) -> dict:
    versoes = pacote.get('versions') or []
    fora = {k: pacote.get(k) for k in CAMPOS}
    fora['versions'] = [{'version_number': v['version_number']} for v in versoes]
    if versoes:
        ultima = versoes[0]
        fora['versions'][0].update(description=ultima.get('description', ''),
                                   icon=ultima.get('icon'),
                                   downloads=ultima.get('downloads', 0),
                                   download_url=ultima.get('download_url'))
    return fora


def refresca_instalados(novo: list):
    """A listagem completa é regenerada em lote e chega a ficar uma hora atrás
    (em 22/09 o StarLevelSystem 1.18.0 saiu às 19:28 e a listagem das 19:29
    ainda dizia 1.17.0). A API por pacote responde na hora; então, para o que
    está instalado — onde uma versão escondida mais importa —, pergunta a ela."""
    try:
        instalados = set(json.loads(LOCK.read_text(encoding='utf-8'))['packages'])
    except (OSError, json.JSONDecodeError, KeyError):
        return                          # sem o lock (rodando sem root), fica a listagem
    por_nome = {p['full_name']: p for p in novo if p['full_name'] in instalados}

    def pergunta(nome):
        dono, curto = nome.split('-', 1)
        pedido = urllib.request.Request(API_PACOTE.format(dono=dono, nome=curto),
                                        headers={'User-Agent': 'heimdall-panel/1.0'})
        try:
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                return nome, json.loads(resposta.read().decode('utf-8'))['latest']
        except Exception:               # noqa: BLE001 — um pacote falhar não para o resto
            return nome, None

    with ThreadPoolExecutor(max_workers=8) as grupo:
        for nome, ultima in grupo.map(pergunta, por_nome):
            if not ultima:
                continue
            pacote = por_nome[nome]
            if any(v['version_number'] == ultima['version_number'] for v in pacote['versions']):
                continue
            pacote['versions'].insert(0, {
                'version_number': ultima['version_number'],
                'description': ultima.get('description', ''),
                'icon': ultima.get('icon'),
                'downloads': ultima.get('downloads', 0),
                'download_url': ultima.get('download_url')})


def main():
    pedido = urllib.request.Request(API, headers={'User-Agent': 'heimdall-panel/1.0',
                                                  'Accept-Encoding': 'gzip'})
    with urllib.request.urlopen(pedido, timeout=180) as resposta:
        bruto = resposta.read()
        if resposta.headers.get('Content-Encoding') == 'gzip':
            bruto = gzip.decompress(bruto)
    novo = [enxuga(p) for p in json.loads(bruto.decode('utf-8'))]
    del bruto
    refresca_instalados(novo)

    if len(novo) < 1000:
        sys.exit(f'a Thunderstore devolveu só {len(novo)} pacotes; não troquei')
    try:
        antigo = len(json.loads(DESTINO.read_text(encoding='utf-8')))
        if len(novo) < antigo * 0.9:
            sys.exit(f'o catálogo novo tem {len(novo)} e o atual {antigo}; não troquei')
    except (OSError, json.JSONDecodeError):
        pass

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    tmp = DESTINO.with_suffix('.novo')
    tmp.write_text(json.dumps(novo, separators=(',', ':')), encoding='utf-8')
    # Mesmo dono da pasta: roda como root pelo executor, mas o resto do repo
    # (varredura, backups) mexe nestes arquivos como diego.
    pasta = DESTINO.parent.stat()
    os.chown(tmp, pasta.st_uid, pasta.st_gid)
    os.chmod(tmp, 0o664)
    tmp.replace(DESTINO)
    print(len(novo))


if __name__ == '__main__':
    main()
