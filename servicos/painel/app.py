"""Heimdall Nexus administration panel.

Roda como o usuario 'painel', que nao pode nada: toda acao vai por pedido ao
executor. Fica atras do nginx, num caminho que nao aparece em lugar nenhum do
site publico.
"""
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer

import nucleo
import sagas
import stories
import atlas
import codigos

BASE = Path(__file__).parent
RAIZ_URL = os.environ.get('PAINEL_RAIZ', '/jarl')
VALIDADE_SESSAO = 12 * 3600
# Site, servidor de jogo e dados persistentes podem viver em qualquer raiz da instalação.
VALHEIM_DIR = Path(os.environ.get('HEIMDALL_VALHEIM_DIR', '/srv/valheim'))
COOKIE_SECURE = os.environ.get('HEIMDALL_PANEL_COOKIE_SECURE', 'true').lower() != 'false'
WEB_DIR = Path(os.environ.get('HEIMDALL_WEB_DIR', '/srv/heimdall-web'))
PANEL_STATE_DIR = Path(os.environ.get('HEIMDALL_PANEL_STATE_DIR', '/var/lib/heimdall-panel'))
# Onde upload e download de arquivo grande se encontram com o executor (em disco).
TROCA = Path(os.environ.get('HEIMDALL_PANEL_SWAP_DIR', str(PANEL_STATE_DIR / 'troca')))
AUDITORIA = Path(os.environ.get('HEIMDALL_PANEL_AUDIT_FILE', '/var/log/heimdall-panel/auditoria.jsonl'))
STATUS_FILE = Path(os.environ.get('HEIMDALL_STATUS_FILE', str(WEB_DIR / 'api/status.json')))
GAME_SERVICE = os.environ.get('HEIMDALL_GAME_SERVICE') or 'heimdall-valheim'

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount(f'{RAIZ_URL}/estatico', StaticFiles(directory=BASE / 'estatico'), name='estatico')
modelos = Jinja2Templates(directory=str(BASE / 'modelos'))
modelos.env.globals['raiz'] = RAIZ_URL
# Static files change with every update; a content hash in their URLs makes
# browsers fetch the new CSS/JS instead of reusing a cached copy.
modelos.env.globals['v'] = hashlib.sha256(b''.join(
    path.read_bytes() for path in sorted((BASE / 'estatico').rglob('*'))
    if path.is_file() and path.suffix in ('.css', '.js'))).hexdigest()[:10]
modelos.env.filters['tamanho'] = nucleo.tamanho_legivel
portaria = nucleo.Portaria()


@app.get('/api/sagas/v1/overview')
async def sagas_public_overview(world: str = '', limit: int = 50, story_limit: int = 6):
    """Public data is filtered again from the latest sharing choices on read."""
    try:
        data = sagas.public_view(world=world, limit=limit)
    except (OSError, ValueError, sagas.sqlite3.Error):
        data = {'available': False, 'worlds': [], 'players': [], 'events': []}
    data['atlas'] = None
    try:
        if data.get('available') and data.get('world'):
            data['atlas'] = atlas.summary(sagas.STATE, data['world'])
    except (OSError, ValueError, sagas.sqlite3.Error):
        data['atlas'] = None
    try:
        data['stories'] = stories.public_list(sagas.DATABASE, data.get('world', ''),
                                             limit=min(20, max(1, story_limit))) \
            if data.get('available') else []
        data['stories_enabled'] = bool(data.get('available') and
            sagas.load_settings(sagas.STATE)['events'] and
            stories.load_config(sagas.STATE)['enabled'])
    except (OSError, ValueError, sagas.sqlite3.Error):
        data['stories'] = []
        data['stories_enabled'] = False
    return JSONResponse(data, headers={'Cache-Control': 'no-store'})


@app.get('/api/sagas/v1/atlas/{world}/{revision}/{z}/{x}/{y}.webp')
async def sagas_public_atlas(world: str, revision: str, z: int, x: int, y: int):
    try:
        content = atlas.tile(sagas.STATE, world, revision, z, x, y)
    except (OSError, ValueError, sagas.sqlite3.Error):
        content = None
    if content is None:
        return Response(status_code=404, headers={'Cache-Control': 'no-store'})
    return Response(content, media_type='image/webp', headers={'Cache-Control': 'no-store'})


def assinador():
    config = nucleo.le_config()
    segredo = config.get('segredo')
    if not segredo:
        raise nucleo.Erro('o painel ainda não tem senha definida (definir-senha.py)')
    return URLSafeTimedSerializer(segredo, salt='sessao-painel')


def quem_e(pedido: Request) -> str | None:
    bolacha = pedido.cookies.get('painel')
    if not bolacha:
        return None
    try:
        dados = assinador().loads(bolacha, max_age=VALIDADE_SESSAO)
    except (BadSignature, nucleo.Erro):
        return None
    return dados.get('usuario')


def exige(pedido: Request):
    usuario = quem_e(pedido)
    if not usuario:
        raise PermissaoNegada()
    return usuario


class PermissaoNegada(Exception):
    pass


@app.exception_handler(PermissaoNegada)
async def sem_permissao(pedido: Request, _):
    if pedido.url.path.startswith(f'{RAIZ_URL}/api/'):
        return JSONResponse({'ok': False, 'erro': 'sessão expirada'}, status_code=401)
    return RedirectResponse(f'{RAIZ_URL}/entrar', status_code=303)


def pagina(pedido, modelo, **contexto):
    usuario = quem_e(pedido)
    resposta = modelos.TemplateResponse(pedido, modelo, {
        'usuario': usuario, 'valheim_dir': str(VALHEIM_DIR), **contexto})
    if usuario:
        marca_admin(resposta)
    return resposta


# Hint for the public site: tells its pages to load the admin dock. It carries no
# secret (the session cookie stays HttpOnly under /jarl); every edit is still
# checked against the real session.
HINT_COOKIE = 'jarl'


def marca_admin(resposta):
    resposta.set_cookie(HINT_COOKIE, '1', max_age=VALIDADE_SESSAO, secure=COOKIE_SECURE,
                        samesite='lax', path='/')


# ---------------------------------------------------------------- entrar
@app.get(f'{RAIZ_URL}/entrar', response_class=HTMLResponse)
async def tela_de_entrada(pedido: Request):
    if quem_e(pedido):
        return RedirectResponse(f'{RAIZ_URL}/', status_code=303)
    return pagina(pedido, 'entrar.html', erro=None,
                  sem_senha=not nucleo.le_config().get('senha'))


@app.post(f'{RAIZ_URL}/entrar', response_class=HTMLResponse)
async def entrar(pedido: Request, senha: str = Form('')):
    ip = (pedido.client.host if pedido.client else '?')
    preso = portaria.barrado(ip)
    if preso:
        return pagina(pedido, 'entrar.html', sem_senha=False,
                      erro=f'Tentativas demais. Espere {preso} segundos.')

    config = nucleo.le_config()
    guardada = config.get('senha')
    if not guardada:
        return pagina(pedido, 'entrar.html', sem_senha=True,
                      erro='Ainda não há senha definida neste painel.')
    if not nucleo.confere_senha(senha, guardada):
        portaria.errou(ip)
        return pagina(pedido, 'entrar.html', sem_senha=False, erro='Senha errada.')

    portaria.acertou(ip)
    resposta = RedirectResponse(f'{RAIZ_URL}/', status_code=303)
    resposta.set_cookie(
        'painel', assinador().dumps({'usuario': config.get('usuario', 'jarl')}),
        max_age=VALIDADE_SESSAO, httponly=True, secure=COOKIE_SECURE, samesite='lax',
        path=RAIZ_URL)
    marca_admin(resposta)
    return resposta


@app.get(f'{RAIZ_URL}/sair')
async def sair(pedido: Request):
    resposta = RedirectResponse(f'{RAIZ_URL}/entrar', status_code=303)
    resposta.delete_cookie('painel', path=RAIZ_URL)
    resposta.delete_cookie(HINT_COOKIE, path='/')
    return resposta


# ---------------------------------------------------------------- páginas
@app.get(RAIZ_URL, response_class=HTMLResponse)
@app.get(f'{RAIZ_URL}/', response_class=HTMLResponse)
async def console(pedido: Request):
    exige(pedido)
    return pagina(pedido, 'console.html', aba='console')


@app.get(f'{RAIZ_URL}/arquivos', response_class=HTMLResponse)
async def arquivos(pedido: Request, caminho: str = str(VALHEIM_DIR)):
    exige(pedido)
    try:
        listagem = await nucleo.pede_async('arquivo.listar', {'caminho': caminho})
        erro = None
    except nucleo.Erro as falha:
        listagem, erro = {'caminho': caminho, 'itens': [], 'acima': None}, str(falha)
    return pagina(pedido, 'arquivos.html', aba='arquivos', listagem=listagem, erro=erro)


@app.get(f'{RAIZ_URL}/mods', response_class=HTMLResponse)
async def mods(pedido: Request):
    exige(pedido)
    return pagina(pedido, 'mods.html', aba='mods', codigos=codigos.CATALOGO)


@app.get(f'{RAIZ_URL}/cronica', response_class=HTMLResponse)
async def cronica(pedido: Request):
    exige(pedido)
    return pagina(pedido, 'cronica.html', aba='cronica')


@app.get(f'{RAIZ_URL}/sagas', response_class=HTMLResponse)
async def sagas_admin(pedido: Request):
    exige(pedido)
    return pagina(pedido, 'sagas.html', aba='sagas', codigos=codigos.CATALOGO)


@app.get(f'{RAIZ_URL}/api/sagas/estado')
async def sagas_admin_estado(pedido: Request):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async('sagas.status', {}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=503)


@app.post(f'{RAIZ_URL}/api/sagas/opcoes')
async def sagas_admin_opcoes(pedido: Request):
    usuario = exige(pedido)
    expected_origin = f'{pedido.url.scheme}://{pedido.headers.get("host", "")}'
    if pedido.headers.get('origin') != expected_origin or \
            not pedido.headers.get('content-type', '').startswith('application/json'):
        return JSONResponse({'ok': False, 'erro': 'origem ou formato inválido'}, status_code=403)
    raw = await pedido.body()
    if len(raw) > 1024:
        return JSONResponse({'ok': False, 'erro': 'pedido grande demais'}, status_code=413)
    try:
        data = json.loads(raw)
        return {'ok': True, **await nucleo.pede_async('sagas.settings.gravar', data, usuario)}
    except (ValueError, nucleo.Erro) as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.get(f'{RAIZ_URL}/sobre', response_class=HTMLResponse)
async def sobre(pedido: Request):
    exige(pedido)
    return pagina(pedido, 'sobre.html', aba='sobre', codigos=codigos.CATALOGO)


@app.get(f'{RAIZ_URL}/api/sistema/atualizacao')
async def sistema_atualizacao_estado(pedido: Request):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async('sistema.estado', {}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=503)


@app.post(f'{RAIZ_URL}/api/sistema/atualizacao')
async def sistema_atualizacao_acao(pedido: Request):
    usuario = exige(pedido)
    expected_origin = f'{pedido.url.scheme}://{pedido.headers.get("host", "")}'
    if pedido.headers.get('origin') != expected_origin or \
            not pedido.headers.get('content-type', '').startswith('application/json'):
        return JSONResponse({'ok': False, 'erro': 'origem ou formato inválido'}, status_code=403)
    raw = await pedido.body()
    if len(raw) > 512:
        return JSONResponse({'ok': False, 'erro': 'pedido grande demais'}, status_code=413)
    try:
        data = json.loads(raw)
        actions = {'checar': 'sistema.checar', 'canal': 'sistema.canal', 'atualizar': 'sistema.atualizar'}
        if not isinstance(data, dict) or data.get('action') not in actions:
            raise ValueError('ação inválida')
        verb = actions[data.pop('action')]
        return {'ok': True, **await nucleo.pede_async(verb, data, usuario)}
    except (ValueError, nucleo.Erro) as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.get(f'{RAIZ_URL}/api/sagas/historias')
async def sagas_historias_estado(pedido: Request):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async('sagas.story.status', {}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=503)


@app.post(f'{RAIZ_URL}/api/sagas/historias')
async def sagas_historias_acao(pedido: Request):
    usuario = exige(pedido)
    expected_origin = f'{pedido.url.scheme}://{pedido.headers.get("host", "")}'
    if pedido.headers.get('origin') != expected_origin or \
            not pedido.headers.get('content-type', '').startswith('application/json'):
        return JSONResponse({'ok': False, 'erro': 'origem ou formato inválido'}, status_code=403)
    raw = await pedido.body()
    if len(raw) > 1024:
        return JSONResponse({'ok': False, 'erro': 'pedido grande demais'}, status_code=413)
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('action') not in ('config', 'key', 'request'):
            raise ValueError('ação inválida')
        action = data.pop('action')
        return {'ok': True, **await nucleo.pede_async('sagas.story.' + action, data, usuario)}
    except (ValueError, nucleo.Erro) as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.get(f'{RAIZ_URL}/api/cronica/sessoes')
async def api_cronica_sessoes(pedido: Request):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async('cronica.sessoes', {}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.get(f'{RAIZ_URL}/api/cronica')
async def api_cronica(pedido: Request, sessao: str = '', tipo: str = '',
                      busca: str = '', limite: int = 500):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async(
            'cronica.ler', {'sessao': sessao, 'tipo': tipo,
                            'busca': busca, 'limite': limite}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.get(f'{RAIZ_URL}/auditoria', response_class=HTMLResponse)
async def auditoria(pedido: Request):
    exige(pedido)
    caminho = AUDITORIA
    linhas = []
    try:
        for bruto in caminho.read_text(encoding='utf-8').splitlines()[-300:]:
            try:
                linhas.append(json.loads(bruto))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return pagina(pedido, 'auditoria.html', aba='auditoria', linhas=list(reversed(linhas)))


# ---------------------------------------------------------------- api
@app.get(f'{RAIZ_URL}/api/estado')
async def api_estado(pedido: Request):
    usuario = exige(pedido)
    fora = {}
    try:
        fora['game'] = await nucleo.pede_async('servico.estado', {'servico': GAME_SERVICE}, usuario)
    except nucleo.Erro as erro:
        fora['game'] = {'erro': str(erro)}
    try:
        publico = json.loads(STATUS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        publico = {}
    try:
        features = json.loads((WEB_DIR / 'api/features.json').read_text()).get('enabled', [])
    except (OSError, ValueError):
        features = []
    return {'ok': True, 'servicos': fora, 'jogo': publico, 'features': features,
            'estado_jogo': estado_do_jogo(fora['game'])}


def estado_do_jogo(servico: dict) -> dict:
    """One status for every Jarl page, from the live systemd state."""
    ativo = servico.get('ActiveState', '')
    if 'erro' in servico:
        return {'codigo': 'desconhecido', 'rotulo': 'Estado indisponível', 'classe': 'meio'}
    if ativo == 'active' and servico.get('Pronto'):
        return {'codigo': 'no-ar', 'rotulo': 'No ar', 'classe': 'viva'}
    if ativo == 'active':
        return {'codigo': 'carregando', 'rotulo': 'Carregando o mundo…', 'classe': 'meio',
                'detalhe': 'O processo subiu; o Valheim ainda está carregando o mundo e os mods.'}
    if ativo in ('activating', 'reloading'):
        return {'codigo': 'iniciando', 'rotulo': 'Iniciando…', 'classe': 'meio'}
    if ativo == 'deactivating':
        return {'codigo': 'parando', 'rotulo': 'Parando e salvando o mundo…', 'classe': 'meio',
                'detalhe': 'O Valheim grava o mundo antes de fechar. Não desligue a máquina agora.'}
    if ativo == 'failed':
        return {'codigo': 'falhou', 'rotulo': 'Falhou ao iniciar', 'classe': 'morta',
                'detalhe': 'Veja o log abaixo para o motivo.'}
    if ativo == 'inactive':
        return {'codigo': 'desligado', 'rotulo': 'Desligado', 'classe': 'morta'}
    return {'codigo': 'desconhecido', 'rotulo': ativo or 'Estado indisponível', 'classe': 'meio'}


@app.get(f'{RAIZ_URL}/api/log')
async def api_log(pedido: Request, servico: str = 'game', linhas: int = 200):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async('log', {
            'servico': GAME_SERVICE if servico == 'game' else servico, 'linhas': linhas}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.post(f'{RAIZ_URL}/api/servico')
async def api_servico(pedido: Request):
    usuario = exige(pedido)
    corpo = await pedido.json()
    try:
        return {'ok': True, **await nucleo.pede_async('servico.acao', {
            'servico': GAME_SERVICE if corpo.get('servico', 'game') == 'game' else corpo.get('servico'),
            'acao': corpo.get('acao')}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.get(f'{RAIZ_URL}/api/mods/instalados')
async def api_mods_instalados(pedido: Request):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async('mods.instalados', {}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.get(f'{RAIZ_URL}/api/mods/procurar')
async def api_mods_procurar(pedido: Request, busca: str = '', pagina_n: int = 0,
                            ordem: str = 'relevancia', so_1_0: str = 'true'):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async('mods.procurar',
                                          {'busca': busca, 'pagina': pagina_n,
                                           'ordem': ordem,
                                           'so_1_0': so_1_0 != 'false'}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.post(f'{RAIZ_URL}/api/mods')
async def api_mods(pedido: Request):
    usuario = exige(pedido)
    corpo = await pedido.json()
    verbo = corpo.get('verbo', '')
    if verbo not in ('mods.instalar', 'mods.atualizar', 'mods.remover',
                     'mods.catalogo.atualizar', 'mods.varredura',
                     'mods.tarefa', 'mods.tarefas'):
        return JSONResponse({'ok': False, 'erro': 'verbo não permitido aqui'}, status_code=400)
    try:
        return {'ok': True, **await nucleo.pede_async(verbo, corpo.get('dados') or {}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.post(f'{RAIZ_URL}/api/arquivo')
async def api_arquivo(pedido: Request):
    usuario = exige(pedido)
    corpo = await pedido.json()
    verbo = corpo.get('verbo', '')
    if verbo not in ('arquivo.ler', 'arquivo.gravar', 'arquivo.apagar',
                     'arquivo.pasta', 'arquivo.renomear', 'arquivo.listar',
                     'arquivo.copiar', 'arquivo.mover', 'arquivo.extrair',
                     'config.listar'):
        return JSONResponse({'ok': False, 'erro': 'verbo não permitido aqui'}, status_code=400)
    try:
        return {'ok': True, **await nucleo.pede_async(verbo, corpo.get('dados') or {}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.get(f'{RAIZ_URL}/configuracoes', response_class=HTMLResponse)
async def configuracoes(pedido: Request):
    exige(pedido)
    return pagina(pedido, 'configuracoes.html', aba='configuracoes')


@app.get(f'{RAIZ_URL}/server-config', response_class=HTMLResponse)
async def server_config(pedido: Request):
    exige(pedido)
    return pagina(pedido, 'server-config.html', aba='server-config', codigos=codigos.CATALOGO)


@app.get(f'{RAIZ_URL}/tarefas', response_class=HTMLResponse)
async def tarefas(pedido: Request):
    exige(pedido)
    return pagina(pedido, 'schedule.html', aba='tarefas')


@app.get(f'{RAIZ_URL}/schedule')
async def schedule_antigo():
    return RedirectResponse(f'{RAIZ_URL}/tarefas', status_code=301)


@app.get(f'{RAIZ_URL}/backups', response_class=HTMLResponse)
async def backups(pedido: Request):
    exige(pedido)
    return pagina(pedido, 'backups.html', aba='backups')


@app.post(f'{RAIZ_URL}/api/administracao')
async def api_administracao(pedido: Request):
    usuario = exige(pedido)
    expected_origin = f'{pedido.url.scheme}://{pedido.headers.get("host", "")}'
    if pedido.headers.get('origin') not in (None, expected_origin) or \
            not pedido.headers.get('content-type', '').startswith('application/json'):
        return JSONResponse({'ok': False, 'erro': 'pedido inválido'}, status_code=400)
    body = await pedido.json()
    verb = body.get('verbo')
    if verb not in {'server.config', 'server.acesso', 'server.reinstall', 'schedules', 'backups'}:
        return JSONResponse({'ok': False, 'erro': 'ação inválida'}, status_code=400)
    try:
        return {'ok': True, **await nucleo.pede_async(verb, body.get('dados') or {}, usuario)}
    except nucleo.Erro as error:
        return JSONResponse({'ok': False, 'erro': str(error)}, status_code=400)


@app.get(f'{RAIZ_URL}/mundo', response_class=HTMLResponse)
async def mundo(pedido: Request):
    exige(pedido)
    return pagina(pedido, 'mundo.html', aba='mundo')


@app.post(f'{RAIZ_URL}/api/mundo')
async def api_mundo(pedido: Request):
    usuario = exige(pedido)
    corpo = await pedido.json()
    verbo = corpo.get('verbo', '')
    # A tarefa (wipe, instalar) roda no executor; o andamento sai pelo mesmo verbo dos mods.
    if verbo == 'tarefa':
        verbo = 'mods.tarefa'
    if verbo not in ('mundo.estado', 'mundo.seed', 'mundo.wipe', 'mods.tarefa'):
        return JSONResponse({'ok': False, 'erro': 'verbo não permitido aqui'}, status_code=400)
    try:
        return {'ok': True, **await nucleo.pede_async(verbo, corpo.get('dados') or {}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.get(f'{RAIZ_URL}/api/baixar')
async def api_baixar(pedido: Request, caminho: str):
    usuario = exige(pedido)
    try:
        pronto = await nucleo.pede_async('arquivo.preparar_download', {'caminho': caminho}, usuario)
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)
    pasta = TROCA / pronto['ficha']
    # Serve e apaga: a cópia só existe para esta entrega.
    return FileResponse(pasta / pronto['nome'], filename=pronto['nome'],
                        media_type='application/octet-stream',
                        background=BackgroundTask(shutil.rmtree, pasta, ignore_errors=True))


@app.post(f'{RAIZ_URL}/api/enviar')
async def api_enviar(pedido: Request):
    """Recebe um arquivo e entrega ao executor: para uma pasta, ou como mundo novo."""
    usuario = exige(pedido)
    formulario = await pedido.form(max_files=1, max_fields=10)
    arquivo = formulario.get('arquivo')
    if arquivo is None or not getattr(arquivo, 'filename', None):
        return JSONResponse({'ok': False, 'erro': 'nenhum arquivo veio'}, status_code=400)
    nome = Path(arquivo.filename.replace('\\', '/')).name
    if not nome or nome in ('.', '..') or not re.fullmatch(r'[^/\0]{1,200}', nome):
        return JSONResponse({'ok': False, 'erro': 'nome de arquivo inválido'}, status_code=400)
    ficha = uuid.uuid4().hex
    pasta = TROCA / ficha
    pasta.mkdir(mode=0o770)
    try:
        with (pasta / nome).open('wb') as saida:
            while bloco := await arquivo.read(1024 * 1024):
                saida.write(bloco)
    finally:
        await arquivo.close()
    destino = formulario.get('destino', '')
    if destino == 'mundo':
        verbo, dados = 'mundo.instalar', {
            'ficha': ficha, 'nome': nome, 'confirmar': formulario.get('confirmar', ''),
            'religar': formulario.get('religar') != '0'}
    else:
        verbo, dados = 'arquivo.receber', {
            'ficha': ficha, 'nome': nome, 'pasta': destino,
            'substituir': formulario.get('substituir') == '1'}
    try:
        return {'ok': True, **await nucleo.pede_async(verbo, dados, usuario)}
    except nucleo.Erro as erro:
        shutil.rmtree(pasta, ignore_errors=True)
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


# ---------------------------------------------------------------- site
@app.get(f'{RAIZ_URL}/site', response_class=HTMLResponse)
async def site(pedido: Request):
    exige(pedido)
    return pagina(pedido, 'site.html', aba='site')


@app.get(f'{RAIZ_URL}/editor', response_class=HTMLResponse)
async def editor(pedido: Request):
    """Full-screen site editor: tools in a left sidebar, the page in a frame."""
    exige(pedido)
    return pagina(pedido, 'editor.html', aba='site')


@app.get(f'{RAIZ_URL}/aparencia', response_class=HTMLResponse)
async def aparencia(pedido: Request):
    exige(pedido)
    return pagina(pedido, 'aparencia.html', aba='aparencia')


@app.get(f'{RAIZ_URL}/api/site/eu')
async def api_site_eu(pedido: Request):
    return {'ok': True, 'usuario': exige(pedido), 'painel': f'{RAIZ_URL}/'}


@app.get(f'{RAIZ_URL}/api/site/paginas')
async def api_site_paginas(pedido: Request):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async('site.paginas', {}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.get(f'{RAIZ_URL}/api/site/navegacao')
async def api_site_navegacao(pedido: Request):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async('site.navegacao', {}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.post(f'{RAIZ_URL}/api/site/navegacao')
async def api_site_navegacao_gravar(pedido: Request):
    usuario = exige(pedido)
    if not pedido.headers.get('content-type', '').startswith('application/json'):
        return JSONResponse({'ok': False, 'erro': 'pedido inválido'}, status_code=400)
    try:
        corpo = await pedido.json()
        return {'ok': True, **await nucleo.pede_async('site.navegacao.gravar', corpo, usuario)}
    except (ValueError, nucleo.Erro) as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


IDENTITY_UPLOAD_LIMIT = 8 * 1024 * 1024


@app.get(f'{RAIZ_URL}/api/site/identidade')
async def api_site_identidade(pedido: Request):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async('site.identidade', {}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.post(f'{RAIZ_URL}/api/site/identidade')
async def api_site_identidade_gravar(pedido: Request):
    """Identity settings plus optional logo/favicon/background images."""
    usuario = exige(pedido)
    if not pedido.headers.get('content-type', '').startswith('multipart/form-data'):
        return JSONResponse({'ok': False, 'erro': 'pedido inválido'}, status_code=400)
    formulario = await pedido.form(max_files=3, max_fields=5)
    try:
        dados = json.loads(str(formulario.get('dados') or '{}'))
        if not isinstance(dados, dict):
            raise ValueError
    except ValueError:
        return JSONResponse({'ok': False, 'erro': 'dados inválidos'}, status_code=400)
    ficha = uuid.uuid4().hex
    arquivos = {}
    try:
        for campo in ('logo', 'favicon', 'fundo'):
            arquivo = formulario.get(campo)
            if arquivo is None or not getattr(arquivo, 'filename', None):
                continue
            pasta = TROCA / ficha
            pasta.mkdir(mode=0o770, exist_ok=True)
            total = 0
            with (pasta / campo).open('wb') as saida:
                while bloco := await arquivo.read(256 * 1024):
                    total += len(bloco)
                    if total > IDENTITY_UPLOAD_LIMIT:
                        return JSONResponse({'ok': False, 'erro': f'{campo}: arquivo grande demais'},
                                            status_code=400)
                    saida.write(bloco)
            arquivos[campo] = campo
        if arquivos:
            dados['ficha'], dados['arquivos'] = ficha, arquivos
        dados.pop('_quem', None)
        return {'ok': True, **await nucleo.pede_async('site.identidade.gravar', dados, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)
    finally:
        shutil.rmtree(TROCA / ficha, ignore_errors=True)


@app.post(f'{RAIZ_URL}/api/site/pagina')
async def api_site_pagina(pedido: Request):
    usuario = exige(pedido)
    if not pedido.headers.get('content-type', '').startswith('application/json'):
        return JSONResponse({'ok': False, 'erro': 'pedido inválido'}, status_code=400)
    corpo = await pedido.json()
    verbo = {'criar': 'site.pagina.criar', 'remover': 'site.pagina.remover'}.get(corpo.get('acao'))
    if not verbo:
        return JSONResponse({'ok': False, 'erro': 'ação inválida'}, status_code=400)
    try:
        return {'ok': True, **await nucleo.pede_async(verbo, corpo.get('dados') or {}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.get(f'{RAIZ_URL}/api/site/campos')
async def api_site_campos(pedido: Request, pagina_id: str = '', url: str = ''):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async(
            'site.campos', {'pagina': pagina_id, 'url': url}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.post(f'{RAIZ_URL}/api/site/gravar')
async def api_site_gravar(pedido: Request):
    usuario = exige(pedido)
    # Only same-origin JSON: a form post from another site cannot set this type.
    if not pedido.headers.get('content-type', '').startswith('application/json'):
        return JSONResponse({'ok': False, 'erro': 'pedido inválido'}, status_code=400)
    corpo = await pedido.json()
    try:
        return {'ok': True, **await nucleo.pede_async('site.gravar', {
            'pagina': corpo.get('pagina', ''), 'url': corpo.get('url', ''),
            'alteracoes': corpo.get('alteracoes') or [],
            'operacoes': corpo.get('operacoes') or []}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


# ---------------------------------------------------------------- versions and previews
def _sem_editor(pagina_html: str, faixa: str) -> str:
    """A page shown for looking only: no search indexing, no editor, a banner on top."""
    cabeca = ('<meta name="robots" content="noindex, nofollow">'
              '<script>window.__jarlEditor = true;</script>')
    aviso = ('<div style="position:fixed;left:0;right:0;top:0;z-index:2147483000;'
             'background:#7d6331;color:#fff6df;font:600 14px Georgia,serif;text-align:center;'
             'padding:8px 12px;box-shadow:0 4px 14px rgba(0,0,0,.5)">' + faixa + '</div>')
    pagina_html = re.sub(r'<head[^>]*>', lambda m: m.group(0) + cabeca, pagina_html, count=1)
    return re.sub(r'<body[^>]*>', lambda m: m.group(0) + aviso, pagina_html, count=1)


@app.get(f'{RAIZ_URL}/api/site/versoes')
async def api_site_versoes(pedido: Request, pagina_id: str = '', url: str = ''):
    usuario = exige(pedido)
    try:
        return {'ok': True, **await nucleo.pede_async(
            'site.versoes', {'pagina': pagina_id, 'url': url}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.get(f'{RAIZ_URL}/site/versao', response_class=HTMLResponse)
async def site_versao(pedido: Request, pagina_id: str = '', versao: str = ''):
    usuario = exige(pedido)
    try:
        d = await nucleo.pede_async('site.versao.ver', {'pagina': pagina_id, 'versao': versao}, usuario)
    except nucleo.Erro as erro:
        return HTMLResponse(f'<p>{erro}</p>', status_code=404)
    quando = d['meta']['quando']
    return HTMLResponse(_sem_editor(d['html'], f'Versão de {quando[:16].replace("T", " ")} UTC — só para ver'))


@app.post(f'{RAIZ_URL}/api/site/restaurar')
async def api_site_restaurar(pedido: Request):
    usuario = exige(pedido)
    if not pedido.headers.get('content-type', '').startswith('application/json'):
        return JSONResponse({'ok': False, 'erro': 'pedido inválido'}, status_code=400)
    corpo = await pedido.json()
    try:
        return {'ok': True, **await nucleo.pede_async('site.versao.restaurar', {
            'pagina': corpo.get('pagina', ''), 'versao': corpo.get('versao', '')}, usuario)}
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)


@app.post(f'{RAIZ_URL}/api/site/previa')
async def api_site_previa(pedido: Request):
    usuario = exige(pedido)
    if not pedido.headers.get('content-type', '').startswith('application/json'):
        return JSONResponse({'ok': False, 'erro': 'pedido inválido'}, status_code=400)
    corpo = await pedido.json()
    try:
        d = await nucleo.pede_async('site.previa', {
            'pagina': corpo.get('pagina', ''), 'url': corpo.get('url', ''),
            'alteracoes': corpo.get('alteracoes') or [],
            'operacoes': corpo.get('operacoes') or []}, usuario)
    except nucleo.Erro as erro:
        return JSONResponse({'ok': False, 'erro': str(erro)}, status_code=400)
    return {'ok': True, 'endereco': f'{RAIZ_URL}/previa/{d["token"]}', 'dias': d['dias']}


@app.get(f'{RAIZ_URL}/previa/{{token}}', response_class=HTMLResponse)
async def previa(token: str):
    """Public on purpose: whoever has the (unguessable, expiring) link can look."""
    try:
        d = await nucleo.pede_async('site.previa.ler', {'token': token}, 'visitante')
    except nucleo.Erro:
        return HTMLResponse('<p style="font-family:Georgia;padding:2rem">Essa prévia expirou ou '
                            'não existe.</p>', status_code=404)
    return HTMLResponse(_sem_editor(d['html'], 'Prévia — estas mudanças ainda não foram publicadas'))
