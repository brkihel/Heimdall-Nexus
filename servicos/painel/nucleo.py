"""Ponte entre o site do painel e o executor, mais a parte de login.

Nada aqui tem privilegio: tudo que muda alguma coisa vira um pedido ao executor,
que decide se atende. Este processo pode ser derrubado sem levar o servidor junto.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

import hostos

CONFIG = hostos.env_path('PAINEL_CONFIG')
SOCKET = hostos.env_value('HEIMDALL_PANEL_SOCKET')

# scrypt com estes parametros leva ~0,1 s por tentativa: rapido para voce, caro
# para quem quiser testar um dicionario inteiro.
# maxmem explicito: o limite padrao do OpenSSL e 32 MB e este custo passa dele.
SCRYPT = dict(n=2 ** 15, r=8, p=1, dklen=32, maxmem=96 * 1024 * 1024)


class Erro(Exception):
    """Falha que pode ser mostrada ao usuario."""


# ---------------------------------------------------------------- config
def le_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def grava_config(dados: dict):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix('.tmp')
    tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding='utf-8')
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG)


# ---------------------------------------------------------------- senha
def cifra_senha(senha: str, sal: bytes | None = None) -> str:
    sal = sal or secrets.token_bytes(16)
    bruto = hashlib.scrypt(senha.encode('utf-8'), salt=sal, **SCRYPT)
    return 'scrypt$' + base64.b64encode(sal).decode() + '$' + base64.b64encode(bruto).decode()


def confere_senha(senha: str, guardada: str) -> bool:
    try:
        marca, sal64, alvo64 = guardada.split('$')
        if marca != 'scrypt':
            return False
        bruto = hashlib.scrypt(senha.encode('utf-8'),
                               salt=base64.b64decode(sal64), **SCRYPT)
    except (ValueError, TypeError):
        return False
    # Comparacao de tempo constante: sem isso, o tempo de resposta entrega o hash.
    return hmac.compare_digest(bruto, base64.b64decode(alvo64))


# ---------------------------------------------------------------- tentativas
class Portaria:
    """Segura quem fica tentando senha. Simples de proposito: cabe na memoria."""

    def __init__(self, tentativas=5, janela=300, castigo=300):
        self.tentativas, self.janela, self.castigo = tentativas, janela, castigo
        self._registro: dict[str, list[float]] = {}
        self._presos: dict[str, float] = {}

    def barrado(self, ip: str) -> int:
        solto = self._presos.get(ip, 0)
        return max(0, int(solto - time.time()))

    def errou(self, ip: str):
        agora = time.time()
        recentes = [t for t in self._registro.get(ip, []) if agora - t < self.janela]
        recentes.append(agora)
        self._registro[ip] = recentes
        if len(recentes) >= self.tentativas:
            self._presos[ip] = agora + self.castigo
            self._registro[ip] = []

    def acertou(self, ip: str):
        self._registro.pop(ip, None)
        self._presos.pop(ip, None)


# ---------------------------------------------------------------- executor
def pede(verbo: str, dados: dict | None = None, quem: str = 'painel') -> dict:
    """Manda um verbo ao executor e devolve os dados, ou levanta Erro."""
    pedido = json.dumps({'verbo': verbo, 'dados': dados or {}, 'quem': quem},
                        ensure_ascii=False).encode('utf-8') + b'\n'
    try:
        with hostos.executor_connect(SOCKET, 300) as ligacao:
            ligacao.sendall(pedido)
            resposta = json.loads(ligacao.makefile('rb').readline())
    except (OSError, json.JSONDecodeError) as erro:
        raise Erro(f'o executor não respondeu ({erro})') from erro
    if not resposta.get('ok'):
        raise Erro(resposta.get('erro', 'recusado'))
    return resposta.get('dados', {})


async def pede_async(verbo: str, dados: dict | None = None, quem: str = 'painel') -> dict:
    """A mesma coisa, fora do laço de eventos.

    A conversa com o executor é bloqueante e pode levar minutos — reiniciar o
    servidor de jogo leva. Chamada direto de dentro de um endpoint async, ela
    segura o laço inteiro do uvicorn e o painel parece travado: o console para
    de atualizar, o estado congela, e só um F5 parece resolver. Por isso toda
    chamada passa por uma linha de execução separada.
    """
    import anyio
    return await anyio.to_thread.run_sync(lambda: pede(verbo, dados, quem))


def tamanho_legivel(bytes_: int) -> str:
    for unidade in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(bytes_) < 1024 or unidade == 'TB':
            return f'{bytes_:.0f} {unidade}' if unidade == 'B' else f'{bytes_:.1f} {unidade}'
        bytes_ /= 1024
    return ''
