"""Leitura e escrita do _main.N.fwl2, os metadados de um mundo do Valheim.

Formato (World.SaveWorldFWLData, conferido no assembly_valheim de 22/09/2026):

    int32 tamanho | pacote:
      [cabeçalho do Riverheim: int32 -1, string id, int32 versão, preset…]   (opcional)
      [int32 versão]                                                          (sem Riverheim)
      string nome | string seed | int32 hash da seed | int64 uid | int32 worldgen
      bool needsDB | int32 n + n strings (chaves globais iniciais) | histórico de jogadores

O cabeçalho do Riverheim não tem formato documentado, então não é interpretado: o
início dos campos do jogo é achado procurando o ponto em que nome e seed se leem
direito E o hash gravado bate com o hash da seed. Isso só acontece no lugar certo.

Mundo novo com seed escolhida = cabeçalho e chaves globais copiados de um fwl2 real,
com nome, seed, hash e uid trocados, needsDB falso e histórico vazio — o mesmo que o
próprio jogo grava quando cria um mundo (ver o DevWorld: só o fwl2, sem .db2).
"""
import random
import string
import struct

RIVERHEIM = 'dev.gurebu.riverheim.stable'


def hash_estavel(texto: str) -> int:
    """StringExtensionMethods.GetStableHashCode, com o estouro de int32 do C#."""
    def i32(x):
        x &= 0xFFFFFFFF
        return x - 0x100000000 if x & 0x80000000 else x
    a = b = 5381
    i = 0
    while i < len(texto) and texto[i] != '\0':
        a = i32(((a << 5) + a) ^ ord(texto[i]))
        if i == len(texto) - 1 or texto[i + 1] == '\0':
            break
        b = i32(((b << 5) + b) ^ ord(texto[i + 1]))
        i += 2
    return i32(a + b * 1566083941)


def _le_str(buf, p):
    tam = desl = 0
    while True:
        if p >= len(buf):
            raise ValueError('fim do buffer')
        byte = buf[p]
        p += 1
        tam |= (byte & 0x7F) << desl
        if not byte & 0x80:
            break
        desl += 7
        if desl > 28:
            raise ValueError('tamanho de string inválido')
    if p + tam > len(buf):
        raise ValueError('string além do fim')
    return buf[p:p + tam].decode('utf-8'), p + tam


def _esc_str(texto: str) -> bytes:
    dados = texto.encode('utf-8')
    tam, saida = len(dados), bytearray()
    while True:
        byte = tam & 0x7F
        tam >>= 7
        saida.append(byte | (0x80 if tam else 0))
        if not tam:
            return bytes(saida) + dados


class Fwl:
    """Um fwl2 lido, com os pedaços necessários para regravá-lo."""

    def __init__(self, bruto: bytes):
        (tam,) = struct.unpack_from('<i', bruto, 0)
        pacote = bruto[4:4 + tam]
        if len(pacote) != tam:
            raise ValueError('fwl2 truncado')
        self.riverheim = struct.unpack_from('<i', pacote, 0)[0] == -1 and RIVERHEIM.encode() in pacote[:64]
        for inicio in range(4, min(len(pacote), 4096)):
            try:
                nome, p = _le_str(pacote, inicio)
                seed, p = _le_str(pacote, p)
                (hash_gravado,) = struct.unpack_from('<i', pacote, p)
            except (ValueError, UnicodeDecodeError, struct.error):
                continue
            # Seed vazia grava 0, não o hash de '' (World: seedName == "" ? 0 : hash).
            if nome and hash_gravado == (hash_estavel(seed) if seed else 0):
                break
        else:
            raise ValueError('não achei nome e seed coerentes no fwl2')
        self.cabecalho = pacote[:inicio]
        self.nome, self.seed = nome, seed
        p += 4
        self.uid, self.worldgen = struct.unpack_from('<qi', pacote, p)
        p += 12
        self.precisa_db = bool(pacote[p])
        p += 1
        (n,) = struct.unpack_from('<i', pacote, p)
        p += 4
        self.chaves = []
        for _ in range(n):
            chave, p = _le_str(pacote, p)
            self.chaves.append(chave)
        self._depois_do_nome = pacote[inicio + len(_esc_str(nome)):]

    def renomeado(self, novo_nome: str) -> bytes:
        """O mesmo mundo com outro nome — só o campo nome muda."""
        pacote = self.cabecalho + _esc_str(novo_nome) + self._depois_do_nome
        return struct.pack('<i', len(pacote)) + pacote

    def mundo_novo(self, nome: str, seed: str) -> bytes:
        """Metadados de um mundo que ainda não existe: o jogo gera a partir da seed."""
        uid = hash_estavel(nome) + random.randint(1, 2**31 - 1)
        pacote = (self.cabecalho + _esc_str(nome) + _esc_str(seed)
                  + struct.pack('<iqi', hash_estavel(seed), uid, self.worldgen)
                  + b'\x00' + self._chaves_sem_repeticao() + struct.pack('<i', 0))
        return struct.pack('<i', len(pacote)) + pacote

    def _chaves_sem_repeticao(self) -> bytes:
        # O mundo antigo acumulou a mesma chave 'preset …' mais de 80 vezes (uma por
        # boot). Mundo novo nasce com cada chave uma vez só, na ordem original.
        unicas = list(dict.fromkeys(self.chaves))
        return struct.pack('<i', len(unicas)) + b''.join(_esc_str(c) for c in unicas)

    def resumo(self) -> dict:
        return {'nome': self.nome, 'seed': self.seed, 'uid': f'{self.uid & 0xFFFFFFFF:08x}',
                'riverheim': self.riverheim, 'precisa_db': self.precisa_db,
                'chaves': self.chaves}


def seed_aleatoria() -> str:
    """Como World.GenerateSeed: 10 letras e números."""
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(10))


def seed_valida(seed: str) -> bool:
    return 1 <= len(seed) <= 32 and all(c.isalnum() or c in '-_' for c in seed)
