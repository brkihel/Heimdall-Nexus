#!/usr/bin/python3
"""O executor: a unica parte do painel que tem privilegio.

Ele escuta num socket de unix e so aceita uma lista fixa de verbos. Nao existe
verbo "rode este comando" — e essa ausencia e a seguranca inteira do painel. O
site roda como um usuario sem poder nenhum e pede as coisas por aqui; se o site
for comprometido, o atacante herda esta lista, e nada alem dela.

Tudo que passa por aqui vai para a auditoria, inclusive o que foi recusado.
"""
import getpass
import hashlib
import grp
import json
import os
import pwd
import shutil
import socket
import socketserver
import subprocess
import time
import sys
import time
import re
import secrets
import tempfile
import threading
import urllib.request
import uuid
import sagas
from datetime import datetime, timezone
from pathlib import Path

VALHEIM_ROOT = Path(os.environ.get('HEIMDALL_VALHEIM_DIR', '/srv/valheim'))
HEIMDALL_STATE_ROOT = Path(os.environ.get('HEIMDALL_STATE_DIR', '/var/lib/heimdall-nexus'))
PANEL_STATE_ROOT = Path(os.environ.get('HEIMDALL_PANEL_STATE_DIR', '/var/lib/heimdall-panel'))
SOCKET = Path(os.environ.get('HEIMDALL_PANEL_SOCKET', '/run/heimdall-panel/executor.sock'))
AUDITORIA = Path(os.environ.get('HEIMDALL_PANEL_AUDIT_FILE', '/var/log/heimdall-panel/auditoria.jsonl'))
GRUPO = os.environ.get('HEIMDALL_PANEL_OS_USER', 'painel')

# Onde o gerenciador de arquivos pode pisar. Fora daqui, nao existe.
RAIZES = [VALHEIM_ROOT, HEIMDALL_STATE_ROOT]
# Guardadas antes de qualquer gravacao ou remocao.
COPIAS = Path(os.environ.get('HEIMDALL_PANEL_BACKUP_DIR', '/var/backups/heimdall-panel'))
TAMANHO_MAX = 8 * 1024 * 1024        # arquivo que o painel aceita ler ou gravar

GAME_SERVICE = os.environ.get('HEIMDALL_GAME_SERVICE') or 'heimdall-valheim'
SERVICOS = {GAME_SERVICE, 'heimdall-status', 'heimdall-saga'}

# ---- mods
RAIZ_REPO = Path(os.environ.get('HEIMDALL_ROOT', Path(__file__).resolve().parents[2]))
# O repositorio e separado por funcao: ferramentas/ tem os scripts de
# operacao, dados/ o que eles leem e escrevem.
FERRAMENTAS = RAIZ_REPO / 'ferramentas'
DADOS = Path(os.environ.get('HEIMDALL_DATA_DIR', str(RAIZ_REPO / 'dados')))
CATALOGO = DADOS / 'catalogs/hexium.json'
# Enxuto, gerado por ferramentas/catalogo-thunderstore.py. As versoes antigas
# vem sem endereco: o da Thunderstore sai do nome e da versao.
CATALOGO_TS = DADOS / 'catalogs/thunderstore.json'
DOWNLOAD_TS = 'https://thunderstore.io/package/download/{dono}/{nome}/{versao}/'
BAIXADOS = DADOS / 'downloads'
LOCK = Path(os.environ.get('HEIMDALL_MODS_LOCK', str(VALHEIM_ROOT / 'current/mods.lock.json')))
API_HEXIUM = 'https://valheim.hexium.gg/api/v1/package/'
# O nome de pacote e a versao entram em linha de comando. Sao conferidos contra
# estas formas antes de chegar perto de um subprocess — e o unico jeito de a
# lista de verbos nao virar, na pratica, um shell.
FORMA_PACOTE = re.compile(r'^[A-Za-z0-9_]{1,64}-[A-Za-z0-9_.]{1,64}$')
FORMA_VERSAO = re.compile(r'^[0-9]{1,4}(\.[0-9]{1,4}){1,3}$')

TAREFAS: dict[str, dict] = {}
TRAVA_TAREFAS = threading.Lock()


def agora():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def audita(quem, verbo, dados, resultado, detalhe=''):
    AUDITORIA.parent.mkdir(parents=True, exist_ok=True)
    linha = {'quando': agora(), 'quem': quem, 'verbo': verbo,
             'dados': dados, 'resultado': resultado}
    if detalhe:
        linha['detalhe'] = detalhe[:500]
    with AUDITORIA.open('a', encoding='utf-8') as arquivo:
        arquivo.write(json.dumps(linha, ensure_ascii=False) + '\n')


class Recusa(Exception):
    """Pedido que nao vou atender, com o motivo em portugues."""


def caminho_seguro(bruto: str) -> Path:
    """Resolve e exige que esteja dentro de uma raiz permitida.

    Resolver ANTES de comparar e o ponto: sem isso, '..' ou um link simbolico
    apontando para /etc passariam pela verificacao e sairiam da jaula.
    """
    if not bruto:
        raise Recusa('caminho vazio')
    alvo = Path(bruto)
    if not alvo.is_absolute():
        raise Recusa('o caminho precisa ser absoluto')
    try:
        real = alvo.resolve(strict=False)
    except OSError as erro:
        raise Recusa(f'caminho ilegível: {erro}') from erro
    for raiz in RAIZES:
        if real == raiz or raiz in real.parents:
            return real
    raise Recusa('fora das pastas que o painel pode tocar')


def guarda_copia(alvo: Path) -> str | None:
    """Copia o arquivo para o porao antes de mexer. Devolve onde guardou."""
    if not alvo.is_file():
        return None
    carimbo = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destino = COPIAS / carimbo / alvo.relative_to('/')
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(alvo, destino)
    return str(destino)


# ---------------------------------------------------------------- verbos
def v_ping(_):
    return {'ok': True, 'quando': agora()}


def v_servico_estado(dados):
    nome = dados.get('servico', GAME_SERVICE)
    if nome not in SERVICOS:
        raise Recusa(f'serviço desconhecido: {nome}')
    saida = subprocess.run(
        ['systemctl', 'show', nome, '--no-page',
         '--property=ActiveState,SubState,ExecMainStartTimestamp,MemoryCurrent,NRestarts'],
        capture_output=True, text=True, timeout=15).stdout
    campos = dict(linha.split('=', 1) for linha in saida.strip().splitlines() if '=' in linha)
    return {'servico': nome, **campos}


def v_servico_acao(dados):
    nome = dados.get('servico', GAME_SERVICE)
    acao = dados.get('acao')
    if nome not in SERVICOS:
        raise Recusa(f'serviço desconhecido: {nome}')
    if acao not in ('start', 'stop', 'restart'):
        raise Recusa('ação precisa ser start, stop ou restart')
    resultado = subprocess.run(['systemctl', acao, nome],
                               capture_output=True, text=True, timeout=240)
    if resultado.returncode != 0:
        raise Recusa(resultado.stderr.strip()[:200] or 'o systemd recusou')
    return {'servico': nome, 'acao': acao}


def v_log(dados):
    nome = dados.get('servico', GAME_SERVICE)
    if nome not in SERVICOS:
        raise Recusa(f'serviço desconhecido: {nome}')
    linhas = min(max(int(dados.get('linhas', 200)), 1), 2000)
    desde = dados.get('desde')
    comando = ['journalctl', '-u', nome, '--no-pager', '-n', str(linhas), '-o', 'short-iso']
    if desde:
        comando += ['--since', str(desde)[:40]]
    saida = subprocess.run(comando, capture_output=True, text=True, timeout=30).stdout
    return {'servico': nome, 'linhas': saida.splitlines()}


def v_arquivo_listar(dados):
    pasta = caminho_seguro(dados.get('caminho', str(VALHEIM_ROOT)))
    if not pasta.is_dir():
        raise Recusa('não é uma pasta')
    itens = []
    for filho in sorted(pasta.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        try:
            info = filho.lstat()
        except OSError:
            continue
        itens.append({
            'nome': filho.name,
            'caminho': str(filho),
            'pasta': filho.is_dir(),
            'link': filho.is_symlink(),
            'tamanho': info.st_size,
            'modificado': int(info.st_mtime),
        })
    return {'caminho': str(pasta), 'itens': itens,
            'acima': str(pasta.parent) if any(
                r in pasta.parents for r in RAIZES) else None}


def v_arquivo_ler(dados):
    alvo = caminho_seguro(dados.get('caminho', ''))
    if not alvo.is_file():
        raise Recusa('não é um arquivo')
    if alvo.stat().st_size > TAMANHO_MAX:
        raise Recusa('arquivo grande demais para abrir no painel')
    bruto = alvo.read_bytes()
    try:
        return {'caminho': str(alvo), 'texto': bruto.decode('utf-8'), 'binario': False}
    except UnicodeDecodeError:
        return {'caminho': str(alvo), 'texto': None, 'binario': True,
                'tamanho': len(bruto)}


def v_arquivo_gravar(dados):
    alvo = caminho_seguro(dados.get('caminho', ''))
    texto = dados.get('texto')
    if texto is None:
        raise Recusa('sem conteúdo')
    if len(texto.encode('utf-8')) > TAMANHO_MAX:
        raise Recusa('conteúdo grande demais')
    copia = guarda_copia(alvo)
    dono = alvo.stat() if alvo.exists() else None
    tmp = alvo.with_name('.' + alvo.name + '.painel')
    tmp.write_text(texto, encoding='utf-8')
    if dono:
        os.chown(tmp, dono.st_uid, dono.st_gid)
        os.chmod(tmp, dono.st_mode & 0o7777)
    else:
        # Arquivo novo herda o dono da pasta: dentro de /srv/valheim isso mantem
        # tudo pertencendo ao usuario valheim, que e o que o jogo exige.
        pai = alvo.parent.stat()
        os.chown(tmp, pai.st_uid, pai.st_gid)
        os.chmod(tmp, 0o644)
    os.replace(tmp, alvo)
    return {'caminho': str(alvo), 'copia': copia}


def v_arquivo_apagar(dados):
    alvo = caminho_seguro(dados.get('caminho', ''))
    if not alvo.exists():
        raise Recusa('não existe')
    if alvo in RAIZES:
        raise Recusa('não apago uma raiz')
    if alvo.is_dir():
        # Pasta so sai vazia: apagar arvore por engano e como se perde um mundo.
        try:
            alvo.rmdir()
        except OSError as erro:
            raise Recusa('a pasta não está vazia') from erro
        return {'caminho': str(alvo), 'copia': None}
    copia = guarda_copia(alvo)
    alvo.unlink()
    return {'caminho': str(alvo), 'copia': copia}


def v_arquivo_pasta(dados):
    alvo = caminho_seguro(dados.get('caminho', ''))
    if alvo.exists():
        raise Recusa('já existe')
    alvo.mkdir(parents=False)
    pai = alvo.parent.stat()
    os.chown(alvo, pai.st_uid, pai.st_gid)
    return {'caminho': str(alvo)}


def v_arquivo_renomear(dados):
    de = caminho_seguro(dados.get('de', ''))
    para = caminho_seguro(dados.get('para', ''))
    if not de.exists():
        raise Recusa('a origem não existe')
    if para.exists():
        raise Recusa('o destino já existe')
    de.rename(para)
    return {'de': str(de), 'para': str(para)}


# ---------------------------------------------------------------- troca e operações de arquivo
# Area onde o painel (sem privilegio) e o executor se encontram para arquivo grande:
# o upload cai aqui antes de ir para o lugar, e o download sai daqui. Fica em disco,
# nao em /run: um mundo ou um zip de plugins nao cabe na RAM ao lado do servidor.
TROCA = Path(os.environ.get('HEIMDALL_PANEL_SWAP_DIR', str(PANEL_STATE_ROOT / 'troca')))
FORMA_FICHA = re.compile(r'^[0-9a-f]{32}$')
FICHA_VALIDADE = 3600                     # segundos até a limpeza apagar
TROCA_MAX = 8 * 1024 ** 3                 # nem download nem extração passam disto
EXTRAIR_MAX_ITENS = 200_000


def _dono_da_pasta(pasta: Path):
    info = pasta.stat()
    return info.st_uid, info.st_gid


def _entrega_ao_dono(alvo: Path, uid: int, gid: int):
    """Tudo que o painel cria dentro de /srv/valheim tem de ser do valheim, senão o
    servidor cai em loop (ver a memória 'config do servidor é do usuário valheim')."""
    caminhos = [alvo] + (list(alvo.rglob('*')) if alvo.is_dir() and not alvo.is_symlink() else [])
    for p in caminhos:
        os.lchown(p, uid, gid)
        if not p.is_symlink():
            os.chmod(p, 0o755 if p.is_dir() else 0o644)


def _nome_livre(pasta: Path, nome: str) -> Path:
    alvo = pasta / nome
    if not alvo.exists():
        return alvo
    base, ponto, ext = nome.partition('.') if not nome.startswith('.') else (nome, '', '')
    for n in range(1, 1000):
        sufixo = ' (cópia)' if n == 1 else f' (cópia {n})'
        candidato = pasta / (f'{base}{sufixo}{ponto}{ext}')
        if not candidato.exists():
            return candidato
    raise Recusa('nome ocupado demais')


def _tamanho_total(alvo: Path) -> int:
    if alvo.is_file():
        return alvo.stat().st_size
    return sum(p.stat().st_size for p in alvo.rglob('*') if p.is_file() and not p.is_symlink())


def _cabe_no_disco(bytes_: int, onde: Path):
    livre = shutil.disk_usage(onde).free
    if bytes_ > livre - 2 * 1024 ** 3:       # sempre sobra 2 GB para o jogo salvar
        raise Recusa(f'não cabe: precisa de {bytes_ // 1024**2} MB e o disco tem {livre // 1024**2} MB livres')


def _limpa_troca():
    agora_ = time.time()
    for ficha in TROCA.iterdir() if TROCA.is_dir() else []:
        try:
            if agora_ - ficha.stat().st_mtime > FICHA_VALIDADE:
                shutil.rmtree(ficha, ignore_errors=True)
        except OSError:
            pass


def _pasta_de_ficha(ficha: str) -> Path:
    if not FORMA_FICHA.match(ficha or ''):
        raise Recusa('ficha com formato estranho')
    pasta = TROCA / ficha
    if not pasta.is_dir() or pasta.is_symlink():
        raise Recusa('essa ficha não existe mais (passou de uma hora?)')
    return pasta


def _nome_simples(nome: str) -> str:
    nome = (nome or '').strip()
    if not nome or nome in ('.', '..') or '/' in nome or '\0' in nome or len(nome) > 200:
        raise Recusa('nome de arquivo inválido')
    return nome


def v_arquivo_copiar(dados):
    de = caminho_seguro(dados.get('de', ''))
    pasta = caminho_seguro(dados.get('para', ''))
    if not de.exists():
        raise Recusa('a origem não existe')
    if de in RAIZES:
        raise Recusa('não copio uma raiz')
    if not pasta.is_dir():
        raise Recusa('o destino precisa ser uma pasta')
    if de.is_dir() and (pasta == de or de in pasta.parents):
        raise Recusa('não dá para copiar uma pasta para dentro dela mesma')
    _cabe_no_disco(_tamanho_total(de), pasta)
    alvo = _nome_livre(pasta, de.name)
    if de.is_dir():
        shutil.copytree(de, alvo, symlinks=True)
    else:
        shutil.copy2(de, alvo)
    _entrega_ao_dono(alvo, *_dono_da_pasta(pasta))
    return {'de': str(de), 'para': str(alvo)}


def v_arquivo_mover(dados):
    de = caminho_seguro(dados.get('de', ''))
    pasta = caminho_seguro(dados.get('para', ''))
    if not de.exists():
        raise Recusa('a origem não existe')
    if de in RAIZES:
        raise Recusa('não movo uma raiz')
    if not pasta.is_dir():
        raise Recusa('o destino precisa ser uma pasta')
    if de.is_dir() and (pasta == de or de in pasta.parents):
        raise Recusa('não dá para mover uma pasta para dentro dela mesma')
    alvo = pasta / de.name
    if alvo.exists():
        raise Recusa(f'já existe {de.name} no destino')
    shutil.move(str(de), str(alvo))
    return {'de': str(de), 'para': str(alvo)}


def v_arquivo_extrair(dados):
    import stat
    import zipfile
    arquivo = caminho_seguro(dados.get('caminho', ''))
    if not arquivo.is_file() or not zipfile.is_zipfile(arquivo):
        raise Recusa('só descompacto .zip')
    with zipfile.ZipFile(arquivo) as z:
        itens = z.infolist()
        if len(itens) > EXTRAIR_MAX_ITENS:
            raise Recusa('zip com arquivos demais')
        total = sum(i.file_size for i in itens)
        if total > TROCA_MAX:
            raise Recusa(f'o zip abre em {total // 1024**2} MB — grande demais')
        _cabe_no_disco(total, arquivo.parent)
        for i in itens:
            partes = Path(i.filename.replace('\\', '/')).parts
            if not partes or i.filename.startswith(('/', '\\')) or '..' in partes or ':' in partes[0]:
                raise Recusa(f'o zip tenta sair da pasta: {i.filename}')
            if stat.S_ISLNK(i.external_attr >> 16):
                raise Recusa(f'o zip tem link simbólico: {i.filename}')
        destino = _nome_livre(arquivo.parent, arquivo.stem)
        destino.mkdir()
        try:
            for i in itens:
                alvo = destino.joinpath(*Path(i.filename.replace('\\', '/')).parts)
                if i.is_dir():
                    alvo.mkdir(parents=True, exist_ok=True)
                    continue
                alvo.parent.mkdir(parents=True, exist_ok=True)
                with z.open(i) as origem, alvo.open('wb') as saida:
                    shutil.copyfileobj(origem, saida, 1024 * 1024)
        except BaseException:
            shutil.rmtree(destino, ignore_errors=True)
            raise
    _entrega_ao_dono(destino, *_dono_da_pasta(arquivo.parent))
    return {'caminho': str(arquivo), 'pasta': str(destino), 'itens': len(itens)}


def v_arquivo_preparar_download(dados):
    """Deixa uma cópia na troca, do painel, para ele servir e apagar. Pasta vira zip."""
    import zipfile
    alvo = caminho_seguro(dados.get('caminho', ''))
    if not alvo.exists():
        raise Recusa('não existe')
    total = _tamanho_total(alvo)
    if total > TROCA_MAX:
        raise Recusa(f'{total // 1024**2} MB é grande demais para baixar pelo painel')
    TROCA.mkdir(parents=True, exist_ok=True)
    _limpa_troca()
    _cabe_no_disco(total, TROCA)
    painel = pwd.getpwnam(GRUPO)
    ficha = uuid.uuid4().hex
    pasta = TROCA / ficha
    pasta.mkdir(mode=0o700)
    try:
        if alvo.is_dir():
            nome = alvo.name + '.zip'
            with zipfile.ZipFile(pasta / nome, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                for p in sorted(alvo.rglob('*')):
                    if p.is_symlink():
                        continue
                    z.write(p, p.relative_to(alvo.parent))
        else:
            nome = alvo.name
            shutil.copyfile(alvo, pasta / nome)
    except BaseException:
        shutil.rmtree(pasta, ignore_errors=True)
        raise
    for p in (pasta, pasta / nome):
        os.chown(p, painel.pw_uid, painel.pw_gid)
    return {'ficha': ficha, 'nome': nome, 'tamanho': (pasta / nome).stat().st_size}


def v_arquivo_receber(dados):
    """Leva um upload da troca para a pasta pedida, com o dono da pasta."""
    ficha = _pasta_de_ficha(dados.get('ficha', ''))
    nome = _nome_simples(dados.get('nome', ''))
    origem = ficha / nome
    if not origem.is_file() or origem.is_symlink():
        raise Recusa('o upload não chegou inteiro')
    pasta = caminho_seguro(dados.get('pasta', ''))
    if not pasta.is_dir():
        raise Recusa('o destino precisa ser uma pasta')
    alvo = pasta / nome
    copia = None
    if alvo.exists():
        if not dados.get('substituir') or alvo.is_dir():
            raise Recusa(f'já existe {nome} aqui')
        copia = guarda_copia(alvo)
    tmp = pasta / f'.{nome}.painel'
    shutil.move(str(origem), str(tmp))
    uid, gid = _dono_da_pasta(pasta)
    os.chown(tmp, uid, gid)
    os.chmod(tmp, 0o644)
    os.replace(tmp, alvo)
    shutil.rmtree(ficha, ignore_errors=True)
    return {'caminho': str(alvo), 'copia': copia, 'tamanho': alvo.stat().st_size}


# ---------------------------------------------------------------- mods
# Mod authors shown as "ours" in the mod list (comma separated), e.g. your team name.
NOSSOS = {a.strip() for a in os.environ.get('HEIMDALL_OWN_AUTHORS', '').split(',') if a.strip()}
_CACHE_CATALOGO: dict = {'quando': 0, 'dados': None}


def _le_loja(caminho: Path, loja: str, obrigatorio: bool) -> list:
    try:
        pacotes = json.loads(caminho.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as erro:
        if obrigatorio:
            raise Recusa(f'não consegui ler o catálogo ({erro})') from erro
        return []
    for pacote in pacotes:
        pacote['loja'] = loja
    return pacotes


def _catalogo() -> list:
    """Hexium e Thunderstore numa lista só; relê só quando um dos arquivos muda.

    Pacote que mora nas duas aparece uma vez: vale a loja com a versão mais
    nova, e no empate o Hexium, que é a loja primária do servidor."""
    try:
        marca = (CATALOGO.stat().st_mtime,
                 CATALOGO_TS.stat().st_mtime if CATALOGO_TS.exists() else 0)
    except OSError as erro:
        raise Recusa(f'não achei o catálogo ({erro})') from erro
    if _CACHE_CATALOGO['dados'] is not None and _CACHE_CATALOGO['quando'] == marca:
        return _CACHE_CATALOGO['dados']
    juntos = {p['full_name']: p for p in _le_loja(CATALOGO, 'hexium', True)}
    for pacote in _le_loja(CATALOGO_TS, 'thunderstore', False):
        rival = juntos.get(pacote['full_name'])
        if rival is None or _versao_maior(_ultima(pacote), _ultima(rival)):
            if rival is not None:
                pacote['outra'] = rival
            juntos[pacote['full_name']] = pacote
        else:
            rival['outra'] = pacote
    dados = list(juntos.values())
    _CACHE_CATALOGO.update(quando=marca, dados=dados)
    return dados


def _ultima(pacote: dict) -> str:
    return ((pacote.get('versions') or [{}])[0]).get('version_number') or '0'


def _instalados() -> dict:
    try:
        lock = json.loads(LOCK.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as erro:
        raise Recusa(f'não consegui ler o lock ({erro})') from erro
    return {nome: (p.get('version') or '?')
            for nome, p in lock.get('packages', {}).items()}


def _versao_maior(a: str, b: str) -> bool:
    """a > b, comparando por número e não por texto ('10' não é menor que '9')."""
    def peca(v):
        return [int(x) for x in re.findall(r'\d+', v or '0')[:4]]
    return peca(a) > peca(b)


CRONICA = Path(os.environ.get('HEIMDALL_CHRONICLE_DIR', str(HEIMDALL_STATE_ROOT / 'cronica')))


def v_cronica_sessoes(_):
    """As sessões gravadas, da mais nova para a mais velha."""
    try:
        arquivos = sorted(CRONICA.glob('sessao-*.jsonl'), reverse=True)
    except OSError as erro:
        raise Recusa(f'não consegui ler a pasta das crônicas ({erro})') from erro
    fora = []
    for arquivo in arquivos[:200]:
        try:
            info = arquivo.stat()
        except OSError:
            continue
        fora.append({'nome': arquivo.name, 'tamanho': info.st_size,
                     'quando': int(info.st_mtime)})
    return {'sessoes': fora}


def v_cronica_ler(dados):
    """Uma sessão, filtrada. O arquivo é escolhido pelo nome, nunca por caminho:
    assim não há como pedir a crônica de /etc."""
    nome = str(dados.get('sessao', ''))
    if not re.fullmatch(r'sessao-[0-9T\-]{1,24}Z\.jsonl', nome):
        raise Recusa('nome de sessão inválido')
    arquivo = CRONICA / nome
    if not arquivo.is_file():
        raise Recusa('não achei essa sessão')

    tipo = dados.get('tipo') or ''
    busca = str(dados.get('busca', '')).strip().casefold()
    limite = min(max(int(dados.get('limite', 500)), 1), 5000)

    linhas = []
    try:
        with arquivo.open('r', encoding='utf-8', errors='replace') as aberto:
            for bruto in aberto:
                bruto = bruto.strip()
                if not bruto:
                    continue
                try:
                    evento = json.loads(bruto)
                except json.JSONDecodeError:
                    continue
                if tipo and evento.get('tipo') != tipo:
                    continue
                if busca and busca not in json.dumps(evento, ensure_ascii=False).casefold():
                    continue
                linhas.append(evento)
    except OSError as erro:
        raise Recusa(f'não consegui ler a sessão ({erro})') from erro

    total = len(linhas)
    return {'sessao': nome, 'total': total, 'linhas': linhas[-limite:]}


def v_mods_instalados(_):
    instalados = _instalados()
    catalogo = {p['full_name']: p for p in _catalogo()}
    fora = []
    for nome, versao in sorted(instalados.items()):
        loja = catalogo.get(nome)
        ultima = loja['versions'][0] if loja and loja.get('versions') else None
        autor = nome.split('-', 1)[0]
        # Versao '?' quer dizer que o pacote veio sem manifesto e o log ainda nao
        # tinha a linha dele. Chamar isso de atrasado seria inventar.
        conhecida = versao != '?'
        fora.append({
            'nome': nome,
            'curto': nome.split('-', 1)[-1],
            'autor': autor,
            'versao': versao,
            'ultima': ultima['version_number'] if ultima else None,
            'atrasado': bool(conhecida and ultima
                             and _versao_maior(ultima['version_number'], versao)),
            'na_loja': loja is not None,
            'nosso': autor in NOSSOS,
            'versao_incerta': not conhecida,
            'icone': (loja or {}).get('versions', [{}])[0].get('icon') if loja else None,
            'descricao': (ultima or {}).get('description', ''),
            'url': (loja or {}).get('package_url'),
            'loja': (loja or {}).get('loja'),
        })
    try:
        # A idade que importa e a do catalogo mais velho: e ele que esconde versao.
        idade = int(time.time() - min(c.stat().st_mtime for c in (CATALOGO, CATALOGO_TS)
                                      if c.exists()))
    except OSError:
        idade = None
    return {'mods': fora, 'total': len(fora),
            'atrasados': sum(1 for m in fora if m['atrasado']),
            'catalogo_ha_seg': idade}


PARA_1_0 = 'Valheim 1.0'
ENVELHECIDO = 'Outdated'
ORDENS = ('relevancia', 'rating', 'recentes')


def _relevancia(nome: str, curto: str, descricao: str, busca: str) -> int:
    """Quanto o achado casa com o que foi escrito. Maior e melhor."""
    if not busca:
        return 0
    curto, nome, descricao = curto.casefold(), nome.casefold(), descricao.casefold()
    # Nome de pacote nao tem espaco: 'valheim armory' precisa achar ValheimArmory.
    colada = busca.replace(' ', '')
    if colada != busca and colada in curto:
        busca = colada
    if curto == busca:
        return 100
    if curto.startswith(busca):
        return 80
    if busca in curto:
        return 60
    if busca in nome:
        return 40
    if busca in descricao:
        return 20
    return 0


def v_mods_procurar(dados):
    busca = str(dados.get('busca', '')).strip().casefold()
    pagina = max(int(dados.get('pagina', 0)), 0)
    ordem = dados.get('ordem', 'relevancia')
    if ordem not in ORDENS:
        ordem = 'relevancia'
    so_1_0 = dados.get('so_1_0', True) is not False
    por_pagina = 24
    instalados = _instalados()

    achados = []
    for pacote in _catalogo():
        categorias = pacote.get('categories') or []
        # Depreciado e "Outdated" nunca aparecem: o painel nao deveria facilitar
        # instalar o que a propria loja marcou como passado.
        if pacote.get('is_deprecated') or ENVELHECIDO in categorias:
            continue
        nome = pacote['full_name']
        versao = (pacote.get('versions') or [{}])[0]
        descricao = versao.get('description', '') or ''
        peso = _relevancia(nome, pacote.get('name', ''), descricao, busca)
        if busca and not peso:
            continue
        # O filtro do 1.0 e para navegar, nao para esconder o que foi procurado
        # pelo nome. Um pacote nosso, recem-publicado e ainda sem a etiqueta da
        # loja, sumia da busca — e parecia que o catalogo nao tinha atualizado.
        procurado = peso >= 40 or nome in instalados
        if so_1_0 and PARA_1_0 not in categorias and not procurado:
            continue
        achados.append({
            'nome': nome,
            'curto': pacote.get('name'),
            'autor': pacote.get('owner'),
            'versao': versao.get('version_number'),
            'descricao': descricao,
            'icone': versao.get('icon'),
            'url': pacote.get('package_url'),
            'baixado': versao.get('downloads', 0) or 0,
            'nota': pacote.get('rating_score', 0) or 0,
            'mexido': pacote.get('date_updated') or '',
            'categorias': categorias,
            'loja': pacote.get('loja'),
            'instalado': instalados.get(nome),
            '_peso': peso,
        })

    if ordem == 'rating':
        achados.sort(key=lambda m: (-m['nota'], -m['baixado']))
    elif ordem == 'recentes':
        achados.sort(key=lambda m: m['mexido'], reverse=True)
    else:
        achados.sort(key=lambda m: (-m['_peso'], -m['baixado']))
    for item in achados:
        item.pop('_peso', None)

    recorte = achados[pagina * por_pagina:(pagina + 1) * por_pagina]
    return {'itens': recorte, 'total': len(achados), 'pagina': pagina,
            'ordem': ordem, 'so_1_0': so_1_0,
            'tem_mais': len(achados) > (pagina + 1) * por_pagina}


def v_mods_catalogo_atualizar(_):
    """Rebaixa os catálogos do Hexium e da Thunderstore. Cada um só troca se
    vier íntegro e não encolher; a Thunderstore falhar não desfaz o Hexium."""
    resposta = _atualiza_hexium()
    try:
        feito = subprocess.run(['/usr/bin/python3', str(FERRAMENTAS / 'catalogo-thunderstore.py')],
                               cwd=str(FERRAMENTAS), capture_output=True, text=True, timeout=240)
        if feito.returncode == 0:
            resposta['thunderstore'] = int(feito.stdout.strip().splitlines()[-1])
        else:
            resposta['aviso'] = ('a Thunderstore falhou: '
                                 + (feito.stderr.strip().splitlines() or ['sem detalhe'])[-1][:200])
    except (subprocess.TimeoutExpired, ValueError, IndexError) as erro:
        resposta['aviso'] = f'a Thunderstore falhou: {erro}'
    _CACHE_CATALOGO.update(quando=0, dados=None)     # forca a releitura
    return resposta


def _atualiza_hexium():
    try:
        # gzip corta 5 MB para 500 kB. Nao era o gargalo — o gargalo era o
        # filtro escondendo o resultado — mas nao ha motivo para puxar dez vezes
        # mais bytes do que o necessario.
        pedido = urllib.request.Request(
            API_HEXIUM, headers={'User-Agent': 'heimdall-panel/1.0',
                                 'Accept-Encoding': 'gzip'})
        with urllib.request.urlopen(pedido, timeout=120) as resposta:
            bruto = resposta.read()
            if resposta.headers.get('Content-Encoding') == 'gzip':
                import gzip
                bruto = gzip.decompress(bruto)
            novo = json.loads(bruto.decode('utf-8'))
    except Exception as erro:                              # noqa: BLE001
        raise Recusa(f'o Hexium não respondeu ({erro})') from erro
    if not isinstance(novo, list) or len(novo) < 100:
        raise Recusa('o catálogo veio pequeno demais; não troquei')
    try:
        # A clean installation has no cached catalog yet. Accept the first full
        # download; after that keep the shrink guard so a partial response cannot
        # replace a known-good catalog.
        antigo = _le_loja(CATALOGO, 'hexium', True) if CATALOGO.exists() else []
        if antigo and len(novo) < len(antigo) * 0.9:
            raise Recusa(f'o catálogo novo tem {len(novo)} e o atual {len(antigo)}; não troquei')
    except Recusa:
        raise
    except Exception:                                      # noqa: BLE001
        pass
    tmp = CATALOGO.with_suffix('.novo')
    tmp.write_text(json.dumps(novo), encoding='utf-8')
    # NADA de copystat aqui. Ele preserva a data do arquivo antigo, e a data e
    # justamente como o cache em memoria decide se precisa reler: com ela
    # congelada, o painel servia catalogo velho para sempre, por mais que se
    # clicasse em atualizar. Dono e permissao se resolvem explicitamente.
    try:
        anterior = CATALOGO.stat()
        os.chown(tmp, anterior.st_uid, anterior.st_gid)
        os.chmod(tmp, anterior.st_mode & 0o7777)
    except OSError:
        os.chmod(tmp, 0o644)
    tmp.replace(CATALOGO)
    _CACHE_CATALOGO.update(quando=0, dados=None)     # forca a releitura
    return {'pacotes': len(novo), 'bytes': len(bruto)}


def _acha_versao(nome: str, versao: str) -> dict:
    for pacote in _catalogo():
        if pacote['full_name'] == nome:
            for loja in (pacote, pacote.get('outra')):
                for v in (loja or {}).get('versions', []):
                    if v['version_number'] != versao:
                        continue
                    if not v.get('download_url') and loja['loja'] == 'thunderstore':
                        dono, curto = nome.split('-', 1)
                        return {**v, 'download_url': DOWNLOAD_TS.format(
                            dono=dono, nome=curto, versao=versao)}
                    return v
            raise Recusa(f'{nome} não tem a versão {versao} no catálogo')
    raise Recusa(f'{nome} não está no Hexium nem na Thunderstore')


def _confere_nomes(nome: str, versao: str):
    if not FORMA_PACOTE.match(nome or ''):
        raise Recusa('nome de pacote com formato estranho')
    if not FORMA_VERSAO.match(versao or ''):
        raise Recusa('versão com formato estranho')


def _baixa(nome: str, versao: str) -> Path:
    alvo = BAIXADOS / f'{nome}-{versao}.zip'
    if alvo.is_file() and alvo.stat().st_size > 0:
        return alvo
    endereco = _acha_versao(nome, versao).get('download_url')
    if not endereco or not endereco.startswith('https://'):
        raise Recusa('a loja não deu um endereço de download seguro')
    BAIXADOS.mkdir(parents=True, exist_ok=True)
    tmp = alvo.with_suffix('.parcial')
    pedido = urllib.request.Request(endereco, headers={'User-Agent': 'heimdall-panel/1.0'})
    with urllib.request.urlopen(pedido, timeout=300) as resposta, tmp.open('wb') as arquivo:
        shutil.copyfileobj(resposta, arquivo, 1024 * 256)
    import zipfile
    try:
        with zipfile.ZipFile(tmp) as z:
            if z.testzip() is not None:
                raise Recusa('o zip veio corrompido')
            json.loads(z.read('manifest.json').decode('utf-8-sig'))
    except Recusa:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as erro:                              # noqa: BLE001
        tmp.unlink(missing_ok=True)
        raise Recusa(f'o zip não parece um pacote válido ({erro})') from erro
    tmp.replace(alvo)
    return alvo


def _tarefa(titulo: str, passos):
    """Roda em outra linha de execução e guarda a saída para o painel acompanhar."""
    chave = uuid.uuid4().hex[:12]
    with TRAVA_TAREFAS:
        TAREFAS[chave] = {'id': chave, 'titulo': titulo, 'estado': 'andando',
                          'saida': [], 'comecou': agora()}

    def anota(linha):
        with TRAVA_TAREFAS:
            TAREFAS[chave]['saida'].append(linha)

    def correr():
        try:
            for passo in passos:
                passo(anota)
        except Recusa as erro:
            with TRAVA_TAREFAS:
                TAREFAS[chave].update(estado='recusado', erro=str(erro))
        except Exception as erro:                          # noqa: BLE001
            anota(f'!! {erro}')
            with TRAVA_TAREFAS:
                TAREFAS[chave].update(estado='falhou', erro=str(erro))
        else:
            with TRAVA_TAREFAS:
                TAREFAS[chave].update(estado='pronto')
        finally:
            with TRAVA_TAREFAS:
                TAREFAS[chave]['terminou'] = agora()

    threading.Thread(target=correr, daemon=True).start()
    return chave


def _roda(comando: list[str], anota):
    anota('$ ' + ' '.join(comando))
    processo = subprocess.Popen(comando, cwd=str(FERRAMENTAS), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
    for linha in processo.stdout:
        anota(linha.rstrip())
    processo.wait()
    if processo.returncode != 0:
        raise Recusa(f'o script saiu com código {processo.returncode}')


def v_mods_instalar(dados):
    nome, versao = dados.get('nome', ''), dados.get('versao', '')
    _confere_nomes(nome, versao)
    if nome in _instalados():
        raise Recusa(f'{nome} já está instalado')

    def passos(anota):
        anota(f'baixando {nome} {versao} do Hexium…')
        caminho = _baixa(nome, versao)
        anota(f'zip conferido: {caminho.name} ({caminho.stat().st_size} bytes)')
        _roda(['/usr/bin/python3', str(FERRAMENTAS / 'instalar-mods.py'),
               f'{nome}={caminho.name}'], anota)

    return {'tarefa': _tarefa(f'instalar {nome} {versao}', [passos])}


def v_mods_atualizar(dados):
    nome, versao = dados.get('nome', ''), dados.get('versao', '')
    _confere_nomes(nome, versao)
    if nome not in _instalados():
        raise Recusa(f'{nome} não está instalado')

    def passos(anota):
        anota(f'baixando {nome} {versao} do Hexium…')
        caminho = _baixa(nome, versao)
        anota(f'zip conferido: {caminho.name}')
        _roda(['/usr/bin/python3', str(FERRAMENTAS / 'atualizar-mods.py'),
               f'{nome}={versao}'], anota)

    return {'tarefa': _tarefa(f'atualizar {nome} para {versao}', [passos])}


def v_mods_remover(dados):
    nome = dados.get('nome', '')
    if not FORMA_PACOTE.match(nome or ''):
        raise Recusa('nome de pacote com formato estranho')
    if nome not in _instalados():
        raise Recusa(f'{nome} não está instalado')
    pastas = [VALHEIM_ROOT / 'current/BepInEx/plugins' / nome,
              VALHEIM_ROOT / 'current/BepInEx/patchers' / nome,
              VALHEIM_ROOT / 'current/package-docs' / nome]

    def passos(anota):
        subprocess.run(['systemctl', 'stop', GAME_SERVICE], timeout=240)
        anota('servidor parado')
        carimbo = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        for pasta in pastas:
            if pasta.is_dir():
                guarda = COPIAS / carimbo / pasta.relative_to('/')
                guarda.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(pasta, guarda)
                shutil.rmtree(pasta)
                anota(f'removido {pasta} (cópia em {guarda})')
        _roda(['/usr/bin/python3', str(FERRAMENTAS / 'relock.py')], anota)
        subprocess.run(['systemctl', 'start', GAME_SERVICE], timeout=240)
        anota('servidor religado')

    return {'tarefa': _tarefa(f'remover {nome}', [passos])}


def v_mods_varredura(_):
    """Pergunta a TODAS as lojas, uma por pacote. O catálogo do painel é do
    Hexium; quem mora só na Thunderstore só aparece por aqui."""
    def passos(anota):
        # A varredura compara contra um retrato do lock. Retrato velho acusa
        # atualizacao de mod que ja foi atualizado — foi o que aconteceu em
        # 21/09. Entao o retrato e refeito antes de perguntar as lojas.
        retrato = DADOS / 'mods.lock.current.json'
        shutil.copyfile(LOCK, retrato)
        anota(f'retrato do lock refeito: {len(_instalados())} pacotes')
        anota('perguntando ao Hexium e a Thunderstore, pacote por pacote...')
        _roda(['/usr/bin/python3', str(FERRAMENTAS / 'varredura.py')], anota)

    return {'tarefa': _tarefa('procurar atualizações em todas as lojas', [passos])}


def v_mods_tarefa(dados):
    chave = str(dados.get('id', ''))
    with TRAVA_TAREFAS:
        tarefa = TAREFAS.get(chave)
        if tarefa is None:
            raise Recusa('não conheço essa tarefa')
        return dict(tarefa)


def v_mods_tarefas(_):
    with TRAVA_TAREFAS:
        return {'tarefas': [{k: v for k, v in t.items() if k != 'saida'}
                            for t in sorted(TAREFAS.values(),
                                            key=lambda t: t['comecou'], reverse=True)[:20]]}


# ---------------------------------------------------------------- mundo
# O Valheim 1.0.15 salva o mundo como PASTA: worlds_local/<Nome>/ com os chunks e o
# trio _main.N.db2/.fwl2/.ok. Os mods guardam estado por mundo fora dela — o
# Seasonality pelo nome, o StarLevelSystem pelo uid —, e o ServerCharacters guarda
# os personagens em characters_local. Wipe certo é tirar tudo isso junto, arquivado
# (nada é apagado) em /srv/valheim/wipes/<carimbo>/.
import fwl  # noqa: E402  (mora ao lado deste arquivo)
import sitetext  # noqa: E402  (lives next to this file)
import operacoes  # noqa: E402

VALHEIM = VALHEIM_ROOT
MUNDOS = VALHEIM / 'saves/worlds_local'
PERSONAGENS = VALHEIM / 'saves/characters_local'
WIPES = VALHEIM / 'wipes'
CONFIG_BEPINEX = VALHEIM / 'config/BepInEx'
PERFIS = Path(os.environ.get('HEIMDALL_PROFILES_DIR', str(HEIMDALL_STATE_ROOT / 'perfis')))
BACKUP = FERRAMENTAS / 'backup.py'
TRAVA_MANUTENCAO = os.environ.get('HEIMDALL_MAINTENANCE_LOCK', '/run/lock/heimdall-maintenance.lock')


def _nome_do_mundo() -> str:
    for linha in (VALHEIM / 'server.env').read_text(encoding='utf-8').splitlines():
        if linha.startswith('VH_WORLD='):
            nome = linha.split('=', 1)[1].strip().strip('"\'')
            if re.fullmatch(r'[A-Za-z0-9_ -]{1,40}', nome):
                return nome
    raise Recusa('não consegui ler VH_WORLD no server.env')


def _fwl_atual(pasta: Path):
    """O fwl2 do save mais recente da pasta, ou None."""
    candidatos = sorted(pasta.glob('_main.*.fwl2'),
                        key=lambda p: int(re.search(r'_main\.(\d+)\.fwl2', p.name).group(1)))
    return candidatos[-1] if candidatos else None


def _servidor_ativo() -> bool:
    return subprocess.run(['systemctl', 'is-active', '--quiet', GAME_SERVICE]).returncode == 0


def _personagens():
    if not PERSONAGENS.is_dir():
        return []
    return sorted(p.name for p in PERSONAGENS.glob('*.fch')
                  if '_backup_auto-' not in p.name)


def v_mundo_estado(_):
    nome = _nome_do_mundo()
    pasta = MUNDOS / nome
    estado = {'mundo': nome, 'existe': pasta.is_dir(), 'ativo': _servidor_ativo(),
              'personagens': _personagens(), 'wipes': []}
    arquivo = _fwl_atual(pasta) if pasta.is_dir() else None
    if arquivo:
        try:
            estado.update(fwl.Fwl(arquivo.read_bytes()).resumo())
        except ValueError as erro:
            estado['erro_fwl'] = str(erro)
        estado['salvo_em'] = int(arquivo.stat().st_mtime)
        estado['gerado'] = any(pasta.glob('_main.*.db2'))
        estado['tamanho'] = _tamanho_total(pasta)
        estado.pop('chaves', None)
    for wipe in sorted(WIPES.iterdir(), reverse=True)[:10] if WIPES.is_dir() else []:
        try:
            estado['wipes'].append(json.loads((wipe / 'wipe.json').read_text(encoding='utf-8')))
        except (OSError, json.JSONDecodeError):
            continue
    return estado


def _para_servidor(anota) -> bool:
    """Para e confere que o mundo foi gravado. Devolve se estava ligado."""
    if not _servidor_ativo():
        anota('servidor já estava parado')
        return False
    marca = time.time() - 5
    anota('parando o servidor (ele salva o mundo ao sair)…')
    subprocess.run(['systemctl', 'stop', GAME_SERVICE], timeout=300)
    if operacoes.online():
        raise Recusa('o servidor não parou')
    frescos = [p for p in MUNDOS.rglob('*.ok') if p.stat().st_mtime >= marca]
    if not frescos:
        raise Recusa('o servidor parou mas não gravou o mundo (nenhum .ok novo); não continuo')
    anota(f'mundo salvo ao parar: {", ".join(sorted(p.name for p in frescos))}')
    return True


def _arquiva(origem: Path, destino: Path, anota):
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origem), str(destino))
    anota(f'arquivado: {origem} → {destino}')


def _arquiva_mundo(nome: str, caixa: Path, anota) -> dict:
    """Tira o mundo e o estado dele que os mods guardam. Devolve o resumo do que saiu."""
    pasta = MUNDOS / nome
    resumo = {}
    arquivo = _fwl_atual(pasta) if pasta.is_dir() else None
    if arquivo:
        resumo = fwl.Fwl(arquivo.read_bytes()).resumo()
        resumo.pop('chaves', None)
    if pasta.is_dir():
        _arquiva(pasta, caixa / 'mundo' / nome, anota)
    for velho in sorted(MUNDOS.glob(f'{nome}_backup_auto-*')):
        _arquiva(velho, caixa / 'mundo' / velho.name, anota)
    estacao = CONFIG_BEPINEX / 'Seasonality/LastSeasonChangeData' / f'{nome}.Seasonality.bin'
    if estacao.exists():
        _arquiva(estacao, caixa / 'estado' / estacao.name, anota)
    if resumo.get('uid'):
        for sls in (CONFIG_BEPINEX / 'StarLevelSystem/SavedData').glob(f'*.{nome}-{resumo["uid"]}.yaml'):
            _arquiva(sls, caixa / 'estado' / sls.name, anota)
    return resumo


def _arquiva_personagens(caixa: Path, anota):
    if PERSONAGENS.is_dir():
        for item in sorted(PERSONAGENS.iterdir()):
            _arquiva(item, caixa / 'personagens' / item.name, anota)
    if PERFIS.is_dir():
        for item in sorted(PERFIS.glob('*.json')):
            _arquiva(item, caixa / 'perfis' / item.name, anota)


def _modelo_fwl(caixa: Path, nome: str):
    """Um fwl2 real deste servidor, para copiar o cabeçalho do Riverheim e as chaves."""
    for pasta in [caixa / 'mundo' / nome, MUNDOS / nome]:
        arquivo = _fwl_atual(pasta) if pasta.is_dir() else None
        if arquivo:
            modelo = fwl.Fwl(arquivo.read_bytes())
            if modelo.riverheim:
                return modelo
    for arquivo in sorted(WIPES.rglob('_main.*.fwl2'), reverse=True) if WIPES.is_dir() else []:
        try:
            modelo = fwl.Fwl(arquivo.read_bytes())
        except ValueError:
            continue
        if modelo.riverheim:
            return modelo
    raise Recusa('não achei um fwl2 com o Riverheim para servir de modelo')


def _cria_mundo_com_seed(nome: str, seed: str, modelo, anota):
    pasta = MUNDOS / nome
    pasta.mkdir()
    (pasta / '_main.0.fwl2').write_bytes(modelo.mundo_novo(nome, seed))
    _entrega_ao_dono(pasta, *_dono_da_pasta(MUNDOS))
    anota(f'mundo novo preparado com a seed {seed}: o servidor gera o terreno ao ligar')


def _abre_caixa(motivo: str, **extra) -> Path:
    carimbo = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    caixa = WIPES / f'{carimbo}-{motivo}'
    caixa.mkdir(parents=True)
    (caixa / 'wipe.json').write_text(json.dumps(
        {'quando': agora(), 'pasta': str(caixa), 'motivo': motivo, **extra},
        ensure_ascii=False, indent=2), encoding='utf-8')
    return caixa


def _fecha_caixa(caixa: Path, **extra):
    meta = json.loads((caixa / 'wipe.json').read_text(encoding='utf-8'))
    meta.update(extra)
    (caixa / 'wipe.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                     encoding='utf-8')
    os.chmod(caixa, 0o750)


def _confere_confirmacao(dados, nome):
    if (dados.get('confirmar') or '').strip() != nome:
        raise Recusa(f'para confirmar, escreva o nome do mundo: {nome}')


def v_mundo_wipe(dados):
    nome = _nome_do_mundo()
    _confere_confirmacao(dados, nome)
    mundo, personagens = bool(dados.get('mundo')), bool(dados.get('personagens'))
    if not (mundo or personagens):
        raise Recusa('marque o mundo, os personagens ou os dois')
    seed = (dados.get('seed') or '').strip()
    if seed and not mundo:
        raise Recusa('seed só faz sentido apagando o mundo')
    if seed and not fwl.seed_valida(seed):
        raise Recusa('seed: até 32 letras, números, - ou _')
    religar = dados.get('religar', True) is not False

    def passos(anota):
        import fcntl
        _para_servidor(anota)
        anota('backup completo antes de mexer (backup.py)…')
        _roda(['/usr/bin/python3', str(BACKUP)], anota)
        trava = open(TRAVA_MANUTENCAO, 'w')
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        caixa = _abre_caixa('wipe', mundo=mundo, personagens=personagens,
                            seed_pedida=seed or None)
        try:
            anterior = {}
            if mundo:
                modelo = _modelo_fwl(caixa, nome) if seed else None
                anterior = _arquiva_mundo(nome, caixa, anota)
                if seed:
                    _cria_mundo_com_seed(nome, seed, modelo, anota)
                else:
                    anota('sem seed: o servidor sorteia uma ao ligar')
            if personagens:
                _arquiva_personagens(caixa, anota)
                anota('personagens arquivados: todo mundo entra com personagem novo '
                      '(o ServerCharacters recusa personagem que já pisou em outro mundo)')
            _fecha_caixa(caixa, mundo_anterior=anterior, concluido=agora())
        finally:
            trava.close()
        if religar:
            subprocess.run(['systemctl', 'start', GAME_SERVICE], timeout=240)
            anota('servidor religado — mundo novo leva alguns minutos para gerar')
        anota(f'tudo o que saiu está em {caixa}')

    titulo = 'wipe de ' + ' e '.join(x for x, s in [('mundo', mundo), ('personagens', personagens)] if s)
    return {'tarefa': _tarefa(titulo, [passos])}


def v_mundo_instalar(dados):
    """Troca o mundo pelo zip enviado (uma pasta de mundo gerada no jogo)."""
    import zipfile
    nome = _nome_do_mundo()
    _confere_confirmacao(dados, nome)
    ficha = _pasta_de_ficha(dados.get('ficha', ''))
    envio = ficha / _nome_simples(dados.get('nome', ''))
    if not envio.is_file() or not zipfile.is_zipfile(envio):
        raise Recusa('mande a pasta do mundo compactada em .zip')
    with zipfile.ZipFile(envio) as z:
        arquivos = [i for i in z.infolist() if not i.is_dir()]
        metas = [i for i in arquivos if re.search(r'(^|/)_main\.\d+\.fwl2$', i.filename)]
        if not metas:
            raise Recusa('o zip não tem _main.N.fwl2 — é a pasta do mundo do Valheim 1.0.15?')
        prefixo = metas[0].filename.rsplit('_main.', 1)[0]
        if any(not i.filename.startswith(prefixo) for i in arquivos):
            raise Recusa('o zip tem mais de uma pasta; mande só a do mundo')
        for i in arquivos:
            resto = i.filename[len(prefixo):]
            if '/' in resto or '\\' in resto or resto in ('', '.', '..'):
                raise Recusa(f'arquivo fora do lugar no zip: {i.filename}')
        maior = max(metas, key=lambda i: int(re.search(r'_main\.(\d+)\.fwl2', i.filename).group(1)))
        meta = fwl.Fwl(z.read(maior))
    if not meta.riverheim and not dados.get('sem_riverheim'):
        raise Recusa('esse mundo não foi gerado com o Riverheim: o terreno seria o do jogo '
                     'padrão. Gere com o modpack instalado.')
    religar = dados.get('religar', True) is not False

    def passos(anota):
        import fcntl
        _para_servidor(anota)
        anota('backup completo antes de mexer (backup.py)…')
        _roda(['/usr/bin/python3', str(BACKUP)], anota)
        trava = open(TRAVA_MANUTENCAO, 'w')
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        caixa = _abre_caixa('mundo-enviado', seed_enviada=meta.seed, nome_no_arquivo=meta.nome)
        try:
            anterior = _arquiva_mundo(nome, caixa, anota)
            pasta = MUNDOS / nome
            pasta.mkdir()
            with zipfile.ZipFile(envio) as z:
                for i in z.infolist():
                    if i.is_dir():
                        continue
                    alvo = pasta / i.filename[len(prefixo):]
                    with z.open(i) as origem, alvo.open('wb') as saida:
                        shutil.copyfileobj(origem, saida, 1024 * 1024)
            if meta.nome != nome:
                # O jogo salva pelo nome gravado no fwl2: sem isto o próximo save iria
                # para worlds_local/<outro nome> e o servidor perderia o mundo de vista.
                for arquivo in pasta.glob('_main.*.fwl2'):
                    arquivo.write_bytes(fwl.Fwl(arquivo.read_bytes()).renomeado(nome))
                anota(f'nome interno trocado de {meta.nome} para {nome}')
            _entrega_ao_dono(pasta, *_dono_da_pasta(MUNDOS))
            anota(f'mundo instalado: seed {meta.seed}')
            _fecha_caixa(caixa, mundo_anterior=anterior, concluido=agora())
        finally:
            trava.close()
            shutil.rmtree(ficha, ignore_errors=True)
        if religar:
            subprocess.run(['systemctl', 'start', GAME_SERVICE], timeout=240)
            anota('servidor religado')
        anota(f'o mundo anterior está em {caixa}')

    return {'tarefa': _tarefa(f'instalar mundo enviado (seed {meta.seed})', [passos])}


def v_mundo_seed(_):
    return {'seed': fwl.seed_aleatoria()}


# ---------------------------------------------------------------- configurações
CONFIG_TIPOS = {'.cfg', '.yml', '.yaml', '.json', '.ini', '.txt', '.toml'}
CONFIG_SOBRAS = re.compile(r'\.(bak|orig|old)\b|\.painel$|\.default\.yml$')


def v_config_listar(dados):
    """Configs dos mods, para a aba Configurações. Cópias .bak ficam de fora."""
    raiz = CONFIG_BEPINEX
    com_copias = bool(dados.get('copias'))
    itens = []
    for arquivo in sorted(raiz.rglob('*')):
        if not arquivo.is_file() or arquivo.is_symlink():
            continue
        relativo = arquivo.relative_to(raiz).as_posix()
        if arquivo.suffix.lower() not in CONFIG_TIPOS and not CONFIG_SOBRAS.search(arquivo.name):
            continue
        copia = bool(CONFIG_SOBRAS.search(arquivo.name))
        if copia and not com_copias:
            continue
        if '/localizations/' in f'/{relativo}' or '/Translations/' in f'/{relativo}':
            continue
        info = arquivo.stat()
        itens.append({'caminho': str(arquivo), 'relativo': relativo, 'tamanho': info.st_size,
                      'modificado': int(info.st_mtime), 'copia': copia})
        if len(itens) >= 3000:
            break
    return {'raiz': str(raiz), 'itens': itens}


# ---------------------------------------------------------------- site
# Site pages are canonical HTML sources listed in site-pages.json. Saving edits
# that HTML directly and publishes it; it never runs a content generator.
SITE_DIR = Path(os.environ.get('HEIMDALL_SITE_DIR', str(RAIZ_REPO / 'site/web')))
SITE_TARGET = re.compile(r'^[a-z0-9-]{1,40}$')
SITE_LOCK = threading.Lock()


def _site_page(dados):
    try:
        if dados.get('pagina'):
            return sitetext.find_page(SITE_DIR, str(dados['pagina']))
        return sitetext.page_for_url(SITE_DIR, str(dados.get('url') or '/'))
    except sitetext.TextError as error:
        raise Recusa(str(error)) from error


def v_site_paginas(_):
    try:
        manifest = sitetext.load_manifest(SITE_DIR)
    except sitetext.TextError as error:
        raise Recusa(str(error)) from error
    return {'paginas': [{'id': p['id'], 'titulo': p['titulo'], 'url': p.get('url'),
                         'somente_leitura': p.get('somente_leitura') or ''}
                        for p in manifest['paginas']]}


def v_site_campos(dados):
    manifest, page = _site_page(dados)
    source = (SITE_DIR / page['fonte']).read_text(encoding='utf-8')
    sections = sitetext.extract(source, sitetext.marker_labels(manifest))
    sections += sitetext.mod_fields(SITE_DIR, page)
    available = sitetext.available_markers(manifest, page)
    destinations = _link_destinations(manifest, page, sections)
    return {'pagina': {'id': page['id'], 'titulo': page['titulo'], 'url': page.get('url'),
                       'somente_leitura': page.get('somente_leitura') or ''},
            'secoes': sitetext.public(sections),
            'blocos': sitetext.blocks(source, available),
            'modelos': [{'chave': k, 'rotulo': v['rotulo'], 'secao': bool(v.get('secao')),
                         'vivo': bool(v.get('vivo')), 'abrirLink': bool(v.get('abrirLink')),
                         'categoria': v.get('categoria') or
                         ('Seções' if v.get('secao') else 'Básicos'), 'html': v['html']}
                        for k, v in (page.get('modelos') or {}).items()],
            'destinos': destinations,
            'valores': _site_values(manifest, page)}


def _site_values(manifest, page) -> list[dict]:
    """The tags this page may use, with what each one prints right now."""
    names = sitetext.available_markers(manifest, page)
    if not names:
        return []
    current = {}
    script = SITE_DIR / 'values.py'
    if script.is_file():
        owner = SITE_DIR.stat()
        run = subprocess.run(['/usr/bin/python3', str(script), '--json'], cwd=str(SITE_DIR),
                             user=owner.st_uid, group=owner.st_gid, capture_output=True,
                             text=True, timeout=30)
        try:
            current = json.loads(run.stdout) if run.returncode == 0 else {}
        except json.JSONDecodeError:
            current = {}
    specs = manifest.get('marcadores') or {}
    return [{'chave': name, 'rotulo': specs[name].get('rotulo', name),
             'descricao': specs[name].get('descricao', ''), 'uso': specs[name].get('uso', 'texto'),
             'valor': str(current.get(name, ''))}
            for name in specs if name in names]


_DESTINATIONS_CACHE: dict = {}


def _page_anchors(other) -> list[tuple[str, str]]:
    """(anchor, title) of a page's sections, cached until its file changes."""
    path = SITE_DIR / other['fonte']
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return []
    hit = _DESTINATIONS_CACHE.get(other['id'])
    if hit and hit[0] == stamp:
        return hit[1]
    anchors = [(s['ancora'], s['titulo']) for s in sitetext.extract(path.read_text(encoding='utf-8'))
               if s.get('ancora') and s['id'] not in ('head', 'mods', 'solto')]
    _DESTINATIONS_CACHE[other['id']] = (stamp, anchors)
    return anchors


def _link_destinations(manifest, page, sections) -> list[dict]:
    """Where a link may point: this page's sections, then every page of the site
    and each of its sections, grouped for the link picker."""
    out = [{'grupo': 'Nesta página', 'rotulo': s['titulo'], 'href': '#' + s['ancora']}
           for s in sections if s.get('ancora') and s['id'] not in ('head', 'mods', 'solto')]
    for other in manifest['paginas']:
        if not other.get('url') or other['id'] == page['id']:
            continue
        out.append({'grupo': other['titulo'], 'rotulo': f"{other['titulo']} (topo da página)",
                    'href': other['url']})
        out += [{'grupo': other['titulo'], 'rotulo': title, 'href': f"{other['url']}#{anchor}"}
                for anchor, title in _page_anchors(other)]
    return out


def _write_as_owner(path: Path, text: str):
    """Atomic write that keeps the file's owner and mode (the site is not root's)."""
    info = path.stat()
    tmp = path.with_name('.' + path.name + '.painel')
    tmp.write_text(text, encoding='utf-8')
    os.chown(tmp, info.st_uid, info.st_gid)
    os.chmod(tmp, info.st_mode & 0o7777)
    os.replace(tmp, path)


# Versions of each page (what was published, and the source that made it) and
# shareable previews of unsaved drafts. Root's; the panel reads them through verbs.
SITE_STATE = PANEL_STATE_ROOT
VERSIONS = SITE_STATE / 'site-versoes'
PREVIEWS = SITE_STATE / 'site-previas'
PREVIEW_DAYS = 7
VERSIONS_KEPT = 100
VERSION_ID = re.compile(r'^\d{8}T\d{6}Z(-\d{1,3})?$')
PREVIEW_TOKEN = re.compile(r'^[0-9a-f]{32}$')
# What a throwaway copy of the site needs to rebuild a page: not the map tiles.
BUILD_SKIP = shutil.ignore_patterns('mapa', 'assets', '__pycache__', '*.bak*', '.*')


def _site_build(page, base: Path | None = None, publish: bool = True) -> list[str]:
    """Publish the page's HTML source as-is; no page generator is run on save.

    The editor source is now the canonical page. A page's optional static data
    files can be listed as publish targets too; importing or refreshing data is
    a deliberate content update, separate from saving page edits.
    """
    base = base or SITE_DIR
    output = []
    targets = page.get('publicar') or []
    if publish and targets:
        if not all(SITE_TARGET.match(t) for t in targets):
            raise Recusa('alvo de publicação inválido no site-pages.json')
        run = subprocess.run(['/usr/bin/python3', str(SITE_DIR / 'publicar.py'), *targets],
                             cwd=str(SITE_DIR), capture_output=True, text=True, timeout=120)
        output.append(f'$ publicar.py {" ".join(targets)}\n{run.stdout}{run.stderr}'.strip())
        if run.returncode != 0:
            raise Recusa(f'a publicação falhou: {(run.stderr or run.stdout).strip()[-300:]}')
    if not publish:
        source = base / page['fonte']
        if not source.is_file():
            raise Recusa(f"fonte da página ausente: {page['fonte']}")
    return output


def _describe(source: str, changes: list, ops: list, page: dict) -> list[str]:
    """What a batch did, in words, for the version list."""
    lines = []
    verbs = {'remover': 'Removeu', 'mover': 'Moveu', 'duplicar': 'Duplicou',
             'estilo': 'Mudou o estilo de', 'link': 'Mudou o link de'}
    models = page.get('modelos') or {}
    created = set()
    for op in ops:
        kind, target = op.get('op'), str(op.get('alvo') or '')
        created |= {str(v) for k, v in (op.get('tokens') or {}).items() if k not in ('vivo', '#id')}
        if kind == 'inserir':
            model = models.get(str(op.get('modelo')), {})
            lines.append(f"Adicionou {model.get('rotulo', 'bloco').lower()} perto de "
                         f"{sitetext.describe(source, target)}")
        elif kind in verbs:
            lines.append(f'{verbs[kind]} {sitetext.describe(source, target)}')
    sections = sitetext.extract(source)
    for change in changes:
        key = str(change.get('campo') or '')
        if key.startswith('mod.'):
            lines.append(f'Mudou a descrição do mod {key[4:]}')
        elif key not in created:
            field = sitetext.find_field(sections, key)
            if field:
                label = field.get('rotulo') or f"«{field['texto'][:60]}»"
                lines.append(f'Editou o texto {label}')
    unique = list(dict.fromkeys(lines))
    return unique[:30] + ([f'e mais {len(unique) - 30} alterações'] if len(unique) > 30 else [])


def _site_compute(manifest, page, dados, base: Path) -> tuple[dict, int, list]:
    """The files a batch would write under base, how many things changed, and a summary."""
    changes = dados.get('alteracoes')
    if not isinstance(changes, list) or len(changes) > 500:
        raise Recusa('lista de alterações inválida')
    ops = dados.get('operacoes') or []
    if not isinstance(ops, list) or len(ops) > 200 or not all(isinstance(o, dict) for o in ops):
        raise Recusa('lista de operações inválida')
    mod_changes = [c for c in changes if str(c.get('campo', '')).startswith('mod.')]
    text_changes = [c for c in changes if c not in mod_changes]
    source_path = base / page['fonte']
    source = source_path.read_text(encoding='utf-8')
    try:
        summary = _describe(source, changes, ops, page)
        new_source, changed = sitetext.apply(
            source, text_changes, sitetext.marker_labels(manifest),
            sitetext.available_markers(manifest, page), ops, page.get('modelos') or {})
        writes = {}
        if new_source != source:
            writes[source_path] = new_source
        if mod_changes:
            if not page.get('mods'):
                raise Recusa('esta página não tem lista de mods')
            mods_changed, mod_writes = sitetext.apply_mods(base, page, mod_changes)
            changed += mods_changed
            writes.update(mod_writes)
    except sitetext.TextError as error:
        raise Recusa(str(error)) from error
    return writes, changed, summary


# ---- versions
def _page_files(page) -> list[str]:
    files = [page['fonte'], *(page.get('arquivos') or [])]
    if page.get('mods'):
        files += [page['mods']['lista'], page['mods']['descricoes']]
    return files


def _version_dirs(page) -> list[Path]:
    folder = VERSIONS / page['id']
    if not folder.is_dir():
        return []
    return sorted((d for d in folder.iterdir() if d.is_dir() and VERSION_ID.match(d.name)),
                  key=lambda d: d.name)


def _snapshot(page, who: str, summary: list[str]) -> str:
    """Keeps the page as it is now on disk: its source files and what was published."""
    folder = VERSIONS / page['id']
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(VERSIONS, 0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    vid, n = stamp, 1
    while (folder / vid).exists():
        vid, n = f'{stamp}-{n}', n + 1
    target = folder / vid
    for rel in _page_files(page):
        dest = target / 'arquivos' / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SITE_DIR / rel, dest)
    if page.get('saida') and (SITE_DIR / page['saida']).is_file():
        shutil.copy2(SITE_DIR / page['saida'], target / 'publicado.html')
    (target / 'meta.json').write_text(json.dumps(
        {'id': vid, 'quando': agora(), 'quem': who, 'resumo': summary,
         'arquivos': _page_files(page)}, ensure_ascii=False), encoding='utf-8')
    for old in _version_dirs(page)[:-VERSIONS_KEPT]:
        shutil.rmtree(old, ignore_errors=True)
    return vid


def _matches_latest(page) -> bool:
    versions = _version_dirs(page)
    if not versions:
        return False
    latest = versions[-1] / 'arquivos'
    return all((latest / rel).is_file() and
               (latest / rel).read_bytes() == (SITE_DIR / rel).read_bytes()
               for rel in _page_files(page))


def _keep_current(page):
    """Before changing a page, make sure what is on disk now can be gone back to."""
    if not _version_dirs(page):
        _snapshot(page, 'sistema', ['Como a página estava antes da primeira edição pelo editor'])
    elif not _matches_latest(page):
        _snapshot(page, 'sistema', ['Mudanças feitas fora do editor (no arquivo ou por script)'])


def _write_and_publish(page, writes: dict) -> list[str]:
    """Writes the files, rebuilds and publishes; puts everything back if that fails."""
    before = {path: path.read_text(encoding='utf-8') for path in writes}
    for path in writes:
        guarda_copia(path)
    for path, text in writes.items():
        _write_as_owner(path, text)
    try:
        return _site_build(page)
    except Exception:
        for path, text in before.items():
            _write_as_owner(path, text)
        try:
            _site_build(page)
        except Exception:                              # noqa: BLE001
            pass
        raise


def v_site_gravar(dados):
    """Applies a batch of edits to one page, rebuilds it and publishes it.

    If the rebuild or the publish fails, the source files go back to what they
    were, so the site never keeps a half-applied edit. Every publish becomes a
    version that can be looked at and restored.
    """
    manifest, page = _site_page(dados)
    if page.get('somente_leitura'):
        raise Recusa(page['somente_leitura'])
    with SITE_LOCK:
        writes, changed, summary = _site_compute(manifest, page, dados, SITE_DIR)
        if not writes:
            return {'alterados': 0, 'publicado': False}
        _keep_current(page)
        output = _write_and_publish(page, writes)
        version = _snapshot(page, str(dados.get('_quem') or '?'), summary or ['Alterações'])
    return {'alterados': changed, 'publicado': True, 'versao': version, 'saida': output}


def v_site_versoes(dados):
    _, page = _site_page(dados)
    items = []
    for folder in reversed(_version_dirs(page)):
        try:
            meta = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        meta['previa'] = (folder / 'publicado.html').is_file()
        items.append(meta)
    return {'pagina': page['id'], 'versoes': items,
            'atual': items[0]['id'] if items and _matches_latest(page) else None}


def _version_folder(page, vid: str) -> Path:
    if not VERSION_ID.match(vid or ''):
        raise Recusa('versão inválida')
    folder = VERSIONS / page['id'] / vid
    if not (folder / 'meta.json').is_file():
        raise Recusa('essa versão não existe mais')
    return folder


def v_site_versao_ver(dados):
    _, page = _site_page(dados)
    folder = _version_folder(page, str(dados.get('versao') or ''))
    html_file = folder / 'publicado.html'
    if not html_file.is_file():
        raise Recusa('essa versão não guardou a página publicada')
    meta = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
    return {'html': html_file.read_text(encoding='utf-8'), 'meta': meta}


def v_site_versao_restaurar(dados):
    _, page = _site_page(dados)
    if page.get('somente_leitura'):
        raise Recusa(page['somente_leitura'])
    folder = _version_folder(page, str(dados.get('versao') or ''))
    meta = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
    with SITE_LOCK:
        writes = {}
        for rel in meta.get('arquivos') or []:
            if rel not in _page_files(page):
                raise Recusa('a versão tem um arquivo que não é desta página')
            writes[SITE_DIR / rel] = (folder / 'arquivos' / rel).read_text(encoding='utf-8')
        _keep_current(page)
        output = _write_and_publish(page, writes)
        when = datetime.fromisoformat(meta['quando']).astimezone().strftime('%d/%m %H:%M')
        version = _snapshot(page, str(dados.get('_quem') or '?'), [f'Restaurou a versão de {when}'])
    return {'restaurada': meta['id'], 'versao': version, 'saida': output}


# ---- previews of drafts
def _clean_previews():
    if not PREVIEWS.is_dir():
        return
    now = time.time()
    for meta_file in PREVIEWS.glob('*.json'):
        try:
            expires = json.loads(meta_file.read_text(encoding='utf-8'))['expira_ts']
        except (OSError, json.JSONDecodeError, KeyError):
            expires = 0
        if expires < now:
            meta_file.unlink(missing_ok=True)
            meta_file.with_suffix('.html').unlink(missing_ok=True)


def v_site_previa(dados):
    """Builds the page with the unsaved edits applied, in a throwaway copy of the
    site, and keeps the result under an unguessable address for a few days."""
    manifest, page = _site_page(dados)
    if page.get('somente_leitura') or not page.get('saida'):
        raise Recusa('esta página não tem prévia')
    _clean_previews()
    owner = SITE_DIR.stat()
    (SITE_STATE / 'tmp').mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=SITE_STATE / 'tmp') as tmp:
        os.chmod(tmp, 0o711)
        base = Path(tmp) / 'site'
        shutil.copytree(SITE_DIR, base, ignore=BUILD_SKIP)
        for folder, _, files in os.walk(base):
            os.chown(folder, owner.st_uid, owner.st_gid)
            for name in files:
                os.chown(os.path.join(folder, name), owner.st_uid, owner.st_gid)
        writes, changed, summary = _site_compute(manifest, page, dados, base)
        for path, text in writes.items():
            path.write_text(text, encoding='utf-8')
        _site_build(page, base, publish=False)
        page_html = (base / page['saida']).read_text(encoding='utf-8')
    token = secrets.token_hex(16)
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    os.chmod(PREVIEWS, 0o700)
    expires = time.time() + PREVIEW_DAYS * 86400
    (PREVIEWS / f'{token}.html').write_text(page_html, encoding='utf-8')
    (PREVIEWS / f'{token}.json').write_text(json.dumps(
        {'pagina': page['id'], 'titulo': page['titulo'], 'quem': str(dados.get('_quem') or '?'),
         'criada': agora(), 'expira_ts': expires, 'resumo': summary}, ensure_ascii=False),
        encoding='utf-8')
    return {'token': token, 'alterados': changed, 'dias': PREVIEW_DAYS}


def v_site_previa_ler(dados):
    token = str(dados.get('token') or '')
    if not PREVIEW_TOKEN.match(token):
        raise Recusa('prévia inválida')
    _clean_previews()
    html_file = PREVIEWS / f'{token}.html'
    if not html_file.is_file():
        raise Recusa('essa prévia expirou ou não existe')
    meta = json.loads((PREVIEWS / f'{token}.json').read_text(encoding='utf-8'))
    return {'html': html_file.read_text(encoding='utf-8'), 'meta': meta}


# ---------------------------------------------------------------- site identity and pages
IDENTITY_FILES = {'logo': (5 * 1024 * 1024, {'png', 'jpg', 'webp', 'svg'}),
                  'favicon': (512 * 1024, {'png', 'ico', 'svg'}),
                  'fundo': (8 * 1024 * 1024, {'png', 'jpg', 'webp'})}
RESERVED_SLUGS = {'jarl', 'api', 'assets', 'marca', 'mapa', 'wiki', 'index', 'favicon', 'robots', 'sitemap'}
SLUG = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$')
TOKEN = re.compile(r'^[0-9a-f]{32}$')


def _identity_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('identidade_site', SITE_DIR / 'identidade.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _image_kind(data: bytes) -> str | None:
    """Detect the real image type from its first bytes; never trust the name."""
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    if data[:4] == b'\x00\x00\x01\x00':
        return 'ico'
    head = data[:4096].lstrip().lower()
    if head.startswith(b'<svg') or (head.startswith(b'<?xml') and b'<svg' in head):
        return 'svg'
    return None


def _safe_svg(data: bytes) -> bool:
    text = data.decode('utf-8', errors='replace').lower()
    return not re.search(r'<script|<foreignobject|javascript:|\son[a-z]+\s*=|<iframe|<embed|<object|xlink:href\s*=\s*["\']?(?!#)', text)


def _new_site_file(path: Path, data: bytes):
    """Create a file in the site dir with the same owner/mode as the manifest."""
    ref = (SITE_DIR / sitetext.MANIFEST).stat()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chown(path.parent, ref.st_uid, ref.st_gid)
    os.chmod(path.parent, 0o750)
    tmp = path.with_name('.' + path.name + '.painel')
    tmp.write_bytes(data)
    os.chown(tmp, ref.st_uid, ref.st_gid)
    os.chmod(tmp, ref.st_mode & 0o666)
    os.replace(tmp, path)


def _publish(targets: list[str]) -> list[str]:
    run = subprocess.run(['/usr/bin/python3', str(SITE_DIR / 'publicar.py'), *targets],
                         cwd=str(SITE_DIR), capture_output=True, text=True, timeout=300)
    if run.returncode != 0:
        raise Recusa(f'a publicação falhou: {(run.stderr or run.stdout).strip()[-300:]}')
    return [line for line in run.stdout.splitlines() if line.strip()]


def v_site_identidade(_):
    module = _identity_module()
    return {'identidade': module.carregar(SITE_DIR),
            'cores': [{'chave': k, 'variavel': v, 'rotulo': r, 'padrao': d} for k, v, r, d in module.CORES],
            'paletas': module.PALETAS}


def v_site_identidade_gravar(dados):
    """Save identity, apply it to every page source and publish the whole site."""
    module = _identity_module()
    current = module.carregar(SITE_DIR)
    wanted = {**current, **{k: dados[k] for k in ('nome', 'slogan', 'rodape', 'url', 'cores') if k in dados}}
    for field in IDENTITY_FILES:
        if dados.get('remover_' + field):
            wanted[field] = '' if field != 'favicon' else '/marca/favicon.svg'
    uploads = dados.get('arquivos') or {}
    ficha = str(dados.get('ficha') or '')
    new_files = {}
    try:
        if uploads:
            if not TOKEN.fullmatch(ficha) or not isinstance(uploads, dict):
                raise Recusa('envio de arquivo inválido')
            for field, name in uploads.items():
                if field not in IDENTITY_FILES or not re.fullmatch(r'[a-z]{2,8}', str(name)):
                    raise Recusa('envio de arquivo inválido')
                source = TROCA / ficha / str(name)
                if not source.is_file() or source.is_symlink():
                    raise Recusa('o arquivo enviado sumiu; envie de novo')
                limit, kinds = IDENTITY_FILES[field]
                data = source.read_bytes()
                if len(data) > limit:
                    raise Recusa(f'{field}: arquivo grande demais (máximo {limit // 1024} KB)')
                kind = _image_kind(data)
                if kind not in kinds:
                    raise Recusa(f'{field}: use {", ".join(sorted(kinds))}')
                if kind == 'svg' and not _safe_svg(data):
                    raise Recusa(f'{field}: o SVG tem scripts ou links externos; exporte uma versão simples')
                digest = hashlib.sha256(data).hexdigest()[:10]
                new_files[field] = (f'{field}-{digest}.{kind}', data)
                wanted[field] = f'/marca/{field}-{digest}.{kind}'
        try:
            clean = module.validar(wanted)
        except module.IdentidadeErro as error:
            raise Recusa(str(error)) from error
        with SITE_LOCK:
            marca = SITE_DIR / module.MARCA_DIR
            for filename, data in new_files.values():
                _new_site_file(marca / filename, data)
            manifest = sitetext.load_manifest(SITE_DIR)
            sources = [SITE_DIR / page['fonte'] for page in manifest['paginas']]
            sources += [SITE_DIR / tipo['modelo'] for tipo in (manifest.get('tipos') or {}).values()]
            for source in sources:
                if source.is_file():
                    text = source.read_text(encoding='utf-8')
                    changed = module.aplicar(text, clean)
                    if changed != text:
                        guarda_copia(source)
                        _write_as_owner(source, changed)
            identity_path = SITE_DIR / module.ARQUIVO
            guarda_copia(identity_path)
            _new_site_file(identity_path, (json.dumps(clean, ensure_ascii=False, indent=2) + '\n').encode())
            # Files replaced by a new upload are no longer referenced.
            keep = {Path(clean[f]).name for f in IDENTITY_FILES if clean.get(f)}
            for old in marca.glob('*'):
                if old.name.split('-', 1)[0] in IDENTITY_FILES and old.name not in keep:
                    guarda_copia(old)
                    old.unlink()
            output = _publish([])
    finally:
        if TOKEN.fullmatch(ficha):
            shutil.rmtree(TROCA / ficha, ignore_errors=True)
    return {'identidade': clean, 'saida': output[-20:]}


def _fresh_ids(source: str) -> str:
    source = re.sub(r'data-bloco="[0-9a-f]{8}"', lambda _m: f'data-bloco="{secrets.token_hex(4)}"', source)
    return re.sub(r'data-campo="[0-9a-f]{8}"', lambda _m: f'data-campo="{secrets.token_hex(4)}"', source)


def v_site_pagina_criar(dados):
    import html as html_lib
    title = str(dados.get('titulo') or '').strip()
    slug = str(dados.get('endereco') or '').strip().strip('/').lower()
    kind = str(dados.get('tipo') or '')
    description = str(dados.get('descricao') or '').strip() or f'{title}.'
    if not 1 <= len(title) <= 60 or any(ord(c) < 32 for c in title):
        raise Recusa('dê um título de 1 a 60 caracteres')
    if len(description) > 200 or any(ord(c) < 32 for c in description):
        raise Recusa('a descrição tem no máximo 200 caracteres')
    if not SLUG.fullmatch(slug) or slug in RESERVED_SLUGS:
        raise Recusa('endereço inválido: use letras minúsculas, números e hífens (ex.: regras)')
    with SITE_LOCK:
        manifest = sitetext.load_manifest(SITE_DIR)
        tipos = manifest.get('tipos') or {}
        if kind not in tipos:
            raise Recusa('tipo de página desconhecido')
        url = f'/{slug}/'
        if any(p['id'] == slug or p.get('url') == url for p in manifest['paginas']):
            raise Recusa('já existe uma página com esse endereço')
        template = (SITE_DIR / tipos[kind]['modelo']).read_text(encoding='utf-8')
        page_html = (_fresh_ids(template).replace('{{TITULO}}', html_lib.escape(title))
                     .replace('{{DESCRICAO}}', html_lib.escape(description)).replace('{{CAMINHO}}', url))
        if '{{' in page_html:
            raise Recusa('o modelo da página tem marcadores desconhecidos')
        module = _identity_module()
        page_html = module.aplicar(page_html, module.carregar(SITE_DIR))
        source = f'paginas/{slug}.html'
        _new_site_file(SITE_DIR / source, page_html.encode('utf-8'))
        page = {'id': slug, 'titulo': title, 'url': url, 'fonte': source, 'saida': source, 'tipo': kind,
                'publicar': [slug, 'vivo', 'tema', 'marca'], 'modelos': tipos[kind].get('modelos') or {}}
        manifest['paginas'].append(page)
        manifest_path = SITE_DIR / sitetext.MANIFEST
        guarda_copia(manifest_path)
        _write_as_owner(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        try:
            output = _publish([slug, 'sitemap'])
        except Recusa:
            manifest['paginas'].remove(page)
            _write_as_owner(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
            (SITE_DIR / source).unlink(missing_ok=True)
            raise
    return {'pagina': {'id': slug, 'titulo': title, 'url': url}, 'saida': output}


def v_site_pagina_remover(dados):
    page_id = str(dados.get('pagina') or '')
    with SITE_LOCK:
        manifest = sitetext.load_manifest(SITE_DIR)
        page = next((p for p in manifest['paginas'] if p['id'] == page_id), None)
        if page is None:
            raise Recusa('página não encontrada')
        if page.get('url') == '/':
            raise Recusa('a página inicial não pode ser removida')
        manifest['paginas'].remove(page)
        manifest_path = SITE_DIR / sitetext.MANIFEST
        guarda_copia(manifest_path)
        _write_as_owner(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        source = SITE_DIR / page['fonte']
        copy = guarda_copia(source)
        source.unlink(missing_ok=True)
        output = []
        if page.get('url'):
            output = _publish(['--retirar', page['url']]) + _publish(['sitemap'])
    return {'removida': page_id, 'copia': copy, 'saida': output}


def _operacao(call, *args):
    try:
        return call(*args)
    except operacoes.Problem as error:
        raise Recusa(str(error)) from error


def v_server_config(dados):
    return _operacao(operacoes.server_save, dados) if dados.get('gravar') else operacoes.server_read()


def v_server_reinstall(dados):
    import nucleo
    if not nucleo.confere_senha(str(dados.get('senha_admin') or ''),
                               nucleo.le_config().get('senha', '')):
        raise Recusa('senha do administrador incorreta')
    steam = VALHEIM_ROOT / 'steamcmd/steamcmd.sh'
    game = VALHEIM_ROOT / 'current'
    if not steam.is_file() or not game.is_dir():
        raise Recusa('SteamCMD ou pasta do jogo não encontrados')
    def run(anota):
        if operacoes.online():
            anota('Desligando o servidor antes de reinstalar…')
            _operacao(operacoes._system, 'stop')
            if operacoes.online():
                raise Recusa('o servidor não parou; reinstalação cancelada')
        anota('Reinstalando arquivos oficiais pelo SteamCMD; dados persistentes preservados.')
        result = subprocess.run(['runuser', '-u', 'valheim', '--', str(steam),
                                 '+force_install_dir', str(game), '+login', 'anonymous',
                                 '+app_update', '896660', 'validate', '+quit'],
                                capture_output=True, text=True, timeout=3600)
        if result.returncode:
            raise Recusa((result.stderr or result.stdout)[-500:])
        anota('Arquivos oficiais verificados. O servidor permanece desligado.')
    return {'tarefa': _tarefa('Reinstalar servidor Valheim', [run])}


def v_schedules(dados):
    action = dados.get('acao', 'listar')
    if action == 'listar':
        return {'rotinas': operacoes.schedules_list()}
    if action == 'gravar':
        return {'rotina': _operacao(operacoes.schedules_save, dados.get('rotina') or {})}
    if action == 'apagar':
        _operacao(operacoes.schedules_delete, str(dados.get('id') or ''))
        return {'apagado': True}
    raise Recusa('ação de rotina inválida')


def v_backups(dados):
    action = dados.get('acao', 'listar')
    name = str(dados.get('nome') or '')
    if action == 'listar':
        return {'backups': operacoes.backup_list()}
    if action == 'criar':
        return {'tarefa': _tarefa('Criar backup', [lambda anota: anota(
            'Backup criado: ' + operacoes.backup_create())])}
    if action == 'restaurar':
        _operacao(operacoes._archive, name)
        return {'tarefa': _tarefa('Restaurar backup', [lambda anota: anota(
            'Cópia de segurança anterior: ' + operacoes.backup_restore(name))])}
    if action == 'travar':
        _operacao(operacoes.backup_lock, name, dados.get('travado') is True)
        return {'travado': dados.get('travado') is True}
    if action == 'apagar':
        _operacao(operacoes.backup_delete, name)
        return {'apagado': True}
    raise Recusa('ação de backup inválida')


def v_sagas_settings(_):
    return {'settings': sagas.load_settings(HEIMDALL_STATE_ROOT / 'sagas')}


def v_sagas_status(_):
    status = sagas.admin_status(HEIMDALL_STATE_ROOT / 'sagas', VALHEIM_ROOT)
    try:
        status['importer_timer_active'] = subprocess.run(
            ['systemctl', 'is-active', '--quiet', 'heimdall-sagas-ingest.timer'],
            timeout=3, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        status['importer_timer_active'] = False
    return status


def v_sagas_settings_gravar(dados):
    state = HEIMDALL_STATE_ROOT / 'sagas'
    if not state.is_dir() or not (state / 'settings.json').is_file():
        raise Recusa('instale a extensão antes de alterar suas opções')
    names = ('enabled', 'gear', 'events', 'clock')
    if not isinstance(dados, dict) or set(dados) != set(names) or any(
            not isinstance(dados[name], bool) for name in names):
        raise Recusa('opções da extensão inválidas')
    settings = {'version': 1, **{name: dados[name] for name in names}}
    target = state / 'settings.json'
    temporary = state / ('.settings-' + uuid.uuid4().hex + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    try:
        os.fchown(descriptor, pwd.getpwnam(GRUPO).pw_uid,
                  grp.getgrnam('heimdall-sagas').gr_gid)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
            descriptor = -1
            json.dump(settings, file, ensure_ascii=False, separators=(',', ':'))
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return {'settings': settings}


VERBOS = {
    'sagas.settings': v_sagas_settings,
    'sagas.status': v_sagas_status,
    'sagas.settings.gravar': v_sagas_settings_gravar,
    'server.config': v_server_config,
    'server.reinstall': v_server_reinstall,
    'schedules': v_schedules,
    'backups': v_backups,
    'ping': v_ping,
    'site.paginas': v_site_paginas,
    'site.identidade': v_site_identidade,
    'site.identidade.gravar': v_site_identidade_gravar,
    'site.pagina.criar': v_site_pagina_criar,
    'site.pagina.remover': v_site_pagina_remover,
    'site.campos': v_site_campos,
    'site.gravar': v_site_gravar,
    'site.versoes': v_site_versoes,
    'site.versao.ver': v_site_versao_ver,
    'site.versao.restaurar': v_site_versao_restaurar,
    'site.previa': v_site_previa,
    'site.previa.ler': v_site_previa_ler,
    'cronica.sessoes': v_cronica_sessoes,
    'cronica.ler': v_cronica_ler,
    'mods.instalados': v_mods_instalados,
    'mods.procurar': v_mods_procurar,
    'mods.catalogo.atualizar': v_mods_catalogo_atualizar,
    'mods.instalar': v_mods_instalar,
    'mods.atualizar': v_mods_atualizar,
    'mods.remover': v_mods_remover,
    'mods.varredura': v_mods_varredura,
    'mods.tarefa': v_mods_tarefa,
    'mods.tarefas': v_mods_tarefas,
    'servico.estado': v_servico_estado,
    'servico.acao': v_servico_acao,
    'log': v_log,
    'arquivo.listar': v_arquivo_listar,
    'arquivo.ler': v_arquivo_ler,
    'arquivo.gravar': v_arquivo_gravar,
    'arquivo.apagar': v_arquivo_apagar,
    'arquivo.pasta': v_arquivo_pasta,
    'arquivo.renomear': v_arquivo_renomear,
    'arquivo.copiar': v_arquivo_copiar,
    'arquivo.mover': v_arquivo_mover,
    'arquivo.extrair': v_arquivo_extrair,
    'arquivo.preparar_download': v_arquivo_preparar_download,
    'arquivo.receber': v_arquivo_receber,
    'mundo.estado': v_mundo_estado,
    'mundo.seed': v_mundo_seed,
    'mundo.wipe': v_mundo_wipe,
    'mundo.instalar': v_mundo_instalar,
    'config.listar': v_config_listar,
}


class Atendente(socketserver.StreamRequestHandler):
    timeout = 300

    def handle(self):
        bruto = self.rfile.readline(2 * 1024 * 1024)
        try:
            pedido = json.loads(bruto.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.responde({'ok': False, 'erro': 'pedido ilegível'})
            return

        verbo = pedido.get('verbo', '')
        dados = pedido.get('dados') or {}
        quem = str(pedido.get('quem') or 'desconhecido')[:60]
        funcao = VERBOS.get(verbo)
        if verbo in ('site.gravar', 'site.versao.restaurar', 'site.previa'):
            dados = {**dados, '_quem': quem}
        # Edited HTML would bloat the audit log; record which fields, not their text.
        registro = dados
        if verbo in ('server.config', 'server.reinstall'):
            registro = {'acao': 'gravar' if dados.get('gravar') else 'ler'}
        elif verbo == 'site.gravar' and isinstance(dados.get('alteracoes'), list):
            registro = {'pagina': dados.get('pagina'), 'url': dados.get('url'),
                        'campos': [str(c.get('campo'))[:40] for c in dados['alteracoes']
                                   if isinstance(c, dict)][:100],
                        'operacoes': [f"{o.get('op')}:{o.get('alvo')}" for o in
                                      (dados.get('operacoes') or []) if isinstance(o, dict)][:100]}
        if funcao is None:
            audita(quem, verbo, registro, 'recusado', 'verbo desconhecido')
            self.responde({'ok': False, 'erro': f'não conheço o verbo {verbo}'})
            return
        try:
            resposta = funcao(dados)
        except Recusa as erro:
            audita(quem, verbo, registro, 'recusado', str(erro))
            self.responde({'ok': False, 'erro': str(erro)})
        except Exception as erro:                      # noqa: BLE001
            audita(quem, verbo, registro, 'erro', repr(erro))
            self.responde({'ok': False, 'erro': 'falhou aqui dentro; veja a auditoria'})
        else:
            # Leitura e listagem sao barulho na auditoria: registro so o que muda.
            silenciosos = ('ping', 'servico.estado', 'log', 'arquivo.listar', 'arquivo.ler',
                           'mods.instalados', 'mods.procurar', 'mods.tarefa', 'mods.tarefas',
                           'cronica.sessoes', 'cronica.ler', 'mundo.estado', 'mundo.seed', 'config.listar',
                           'arquivo.preparar_download', 'site.paginas', 'site.campos',
                           'site.versoes', 'site.versao.ver', 'site.previa.ler', 'site.identidade')
            silenciosos += ('sagas.settings', 'sagas.status')
            if verbo not in silenciosos and not (
                verbo == 'server.config' and not dados.get('gravar') or
                verbo in ('schedules', 'backups') and dados.get('acao', 'listar') == 'listar'):
                audita(quem, verbo, registro, 'feito')
            self.responde({'ok': True, 'dados': resposta})

    def responde(self, corpo):
        self.wfile.write(json.dumps(corpo, ensure_ascii=False).encode('utf-8') + b'\n')


class Servidor(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    if os.geteuid() != 0:
        sys.exit('o executor precisa rodar como root — é ele que tem o privilégio')
    SOCKET.parent.mkdir(parents=True, exist_ok=True)
    if SOCKET.exists():
        SOCKET.unlink()
    servidor = Servidor(str(SOCKET), Atendente)
    # So o grupo do painel fala com o executor.
    os.chown(SOCKET, 0, grp.getgrnam(GRUPO).gr_gid)
    os.chmod(SOCKET, 0o660)
    audita('executor', 'iniciou', {}, 'feito')
    print(f'executor ouvindo em {SOCKET}', flush=True)
    servidor.serve_forever()


if __name__ == '__main__':
    main()
