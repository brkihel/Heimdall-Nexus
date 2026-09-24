#!/usr/bin/python3
"""Le os personagens salvos pelo ServerCharacters e gera api/saga.json no site.

Os .fch sao binario cru (nao comprimido, nao cifrado), no formato:
    [int32 tamanho][dados do perfil][int32 64][hash]
O ultimo campo do perfil e o playerData, e dentro dele o bloco de pericias e
    [int32 versao=2][int32 contagem][contagem x (int32 id, float nivel, float acumulado)]
Pericias de mod usam GetStableHashCode(nome) como id, entao o nome so aparece
se estiver no mapa abaixo.
"""
import hashlib, json, os, re, glob, struct, tempfile, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VALHEIM = Path(os.environ.get("HEIMDALL_VALHEIM_DIR", "/srv/valheim"))
WEB = Path(os.environ.get("HEIMDALL_WEB_DIR", "/srv/heimdall-web"))
STATE = Path(os.environ.get("HEIMDALL_STATE_DIR", "/var/lib/heimdall-nexus"))
PERFIS = Path(os.environ.get("HEIMDALL_CHARACTERS_DIR", str(VALHEIM / "saves/characters_local")))
SAIDA = Path(os.environ.get("HEIMDALL_SAGA_FILE", str(WEB / "api/saga.json")))
PLUGINS = Path(os.environ.get("HEIMDALL_BEPINEX_PLUGINS", str(VALHEIM / "current/BepInEx/plugins")))
CACHE = Path(os.environ.get("HEIMDALL_SAGA_CACHE", str(STATE / "pericias-mod.json")))
TZ = ZoneInfo(os.environ.get("HEIMDALL_TIMEZONE", "America/Sao_Paulo"))

VANILLA = {
 1:"Espadas", 2:"Adagas", 3:"Maças", 4:"Lanças longas", 5:"Lanças", 6:"Bloqueio",
 7:"Machados", 8:"Arcos", 9:"Magia de fogo", 10:"Magia de gelo", 11:"Desarmado",
 12:"Picaretas", 13:"Lenhador", 14:"Bestas", 100:"Salto", 101:"Furtividade",
 102:"Corrida", 103:"Natação", 104:"Pesca", 105:"Montaria", 106:"Cozinha",
 107:"Agricultura", 108:"Artesanato",
}
# Pericias de mod nao guardam o nome no save, so o id. O SkillManager que
# praticamente todos usam registra a pericia como
#     (Skills.SkillType)Math.Abs(nomeEmIngles.GetStableHashCode())
# e esse Math.Abs e o motivo de "Hunting" e "Jewelcrafting" nunca baterem por
# hash cru: os dois dao negativo. Em vez de manter uma lista fixa que envelhece
# a cada mod novo, procuro a string que gera o hash dentro das DLLs instaladas.

GRUPO = {
 "combate": {1,2,3,4,5,6,7,8,9,10,11,14},
 "sobrevivencia": {100,101,102,103,105},
 "coleta": {12,13,104,107},
 "oficio": {106,108},
}

def hash_estavel(s):
    n1 = n2 = 5381; i = 0
    while i < len(s):
        n1 = ((n1 << 5) + n1) ^ ord(s[i])
        if i + 1 >= len(s): break
        n2 = ((n2 << 5) + n2) ^ ord(s[i+1])
        i += 2; n1 &= 0xFFFFFFFF; n2 &= 0xFFFFFFFF
    v = (n1 + n2 * 1566083941) & 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v

def acha_player_data(raw):
    """O playerData e o ultimo campo do perfil: o int de tamanho fecha exatamente no fim."""
    tam, = struct.unpack_from("<i", raw, 0)
    fim = 4 + tam
    if fim > len(raw): return None, None
    for pos in range(fim - 8, 8, -1):
        n, = struct.unpack_from("<i", raw, pos)
        if 64 <= n <= tam and pos + 4 + n == fim and raw[pos-1] == 1:
            return raw[pos+4:fim], pos - 1
    return None, None

def acha_nome(raw, limite):
    """O nome do perfil e a ultima string legivel antes do playerData."""
    ini = max(0, limite - 96)
    achado = None
    i = ini
    while i < limite - 1:
        n = raw[i]
        if 2 <= n <= 30 and i + 1 + n <= limite:
            trecho = raw[i+1:i+1+n]
            try: s = trecho.decode("utf-8")
            except UnicodeDecodeError: i += 1; continue
            if re.fullmatch(r"[\w][\w .'-]{1,29}", s, re.UNICODE) and not s.isdigit():
                achado = s
        i += 1
    return achado

def acha_skills(blob):
    melhor = None
    for i in range(len(blob) - 8):
        v, = struct.unpack_from("<i", blob, i)
        if v != 2: continue
        n, = struct.unpack_from("<i", blob, i + 4)
        if not (1 <= n <= 96): continue
        if i + 8 + n * 12 > len(blob): continue
        itens = []; ok = True
        for k in range(n):
            sid, lvl, acc = struct.unpack_from("<iff", blob, i + 8 + k * 12)
            if sid == 0 or not (0.0 <= lvl <= 100.0) or not (0.0 <= acc < 1e7) or acc != acc:
                ok = False; break
            itens.append((sid, lvl, acc))
        if ok and (melhor is None or n > melhor[0]):
            melhor = (n, itens)
    return melhor[1] if melhor else []

NOME_PLAUSIVEL = re.compile(r"[A-Za-z][A-Za-z0-9 _'-]{1,28}\Z")

def assinatura_plugins():
    partes = []
    for d in sorted(Path(PLUGINS).rglob("*.dll")):
        try: st = d.stat()
        except OSError: continue
        partes.append(f"{d}:{st.st_mtime_ns}:{st.st_size}")
    return hashlib.sha256("\n".join(partes).encode()).hexdigest()

def varrer_dlls(alvos):
    """Acha, nas DLLs dos mods, as strings cujo hash bate com os ids pedidos."""
    contagem = {}
    for d in sorted(Path(PLUGINS).rglob("*.dll")):
        try: raw = d.read_bytes()
        except OSError: continue
        cands = set()
        # o heap de strings do .NET guarda UTF-16LE; varro ASCII tambem por seguranca
        for m in re.finditer(rb"(?:[\x20-\x7e]\x00){2,48}", raw):
            cands.add(m.group().decode("utf-16-le"))
        for m in re.finditer(rb"[\x20-\x7e]{2,48}", raw):
            cands.add(m.group().decode("ascii"))
        for txt in cands:
            if not NOME_PLAUSIVEL.match(txt): continue
            h = abs(hash_estavel(txt))
            if h in alvos:
                contagem.setdefault(h, {}).setdefault(txt, 0)
                contagem[h][txt] += 1
    # colisao de hash e possivel: fico com o nome mais repetido e, no empate, o mais curto
    return {h: sorted(c.items(), key=lambda kv: (-kv[1], len(kv[0])))[0][0]
            for h, c in contagem.items()}

def nomes_de_mod(ids):
    cache = {}
    try: cache = json.load(open(CACHE))
    except Exception: pass
    achados = {int(k): v for k, v in cache.get("pericias", {}).items()}
    faltam = {i for i in ids if i not in achados}
    if not faltam: return achados
    assin = assinatura_plugins()
    sem_nome = set(cache.get("sem_nome", []))
    # se ja varri exatamente estes arquivos e nao achei, nao varro de novo
    if assin == cache.get("assinatura") and faltam <= sem_nome:
        return achados
    try: achados.update(varrer_dlls(faltam))
    except Exception: return achados
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CACHE))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"assinatura": assin,
                       "pericias": {str(k): v for k, v in sorted(achados.items())},
                       "sem_nome": sorted(i for i in faltam if i not in achados),
                       "varrido_em": datetime.now(TZ).isoformat(timespec="seconds")},
                      f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o644); os.replace(tmp, CACHE)
    except Exception: pass
    return achados

# As pericias de mod so existem em ingles: o id delas e o hash do nome ingles,
# entao a varredura das DLLs PRECISA do nome original. A traducao entra aqui, na
# hora de exibir, sem tocar no que casa o hash.
# "Lumberjacking" nao vira "Lenhador" de proposito: esse ja e o nome da pericia
# vanilla de corte de arvore (id 13), e as duas aparecem lado a lado na lista.
PT_MOD = {
    "Bee Keeping":   "Apicultura",
    "Blacksmithing": "Ferraria",
    "Explorer":      "Exploração",
    "Herbalist":     "Herbalismo",
    "Hunting":       "Caça",
    "Jewelcrafting": "Joalheria",
    "Lumberjacking": "Madeireiro",
    "Mining":        "Mineração",
    "Ranching":      "Pecuária",
    "Vitality":      "Vitalidade",
    "Wisdom":        "Sabedoria",
}

def grupo_de(sid):
    for g, ids in GRUPO.items():
        if sid in ids: return g
    return "mod" if sid not in VANILLA else "outros"

jogadores = []
brutos = []
# o ServerCharacters grava copias automaticas (_backup_auto-*) e .old no mesmo
# diretorio; sem filtrar, o mesmo jogador aparece varias vezes no ranking.
IGNORAR = re.compile(r"_backup_auto-|_backup-|\.old$", re.I)

for caminho in sorted(glob.glob(os.path.join(PERFIS, "*.fch"))):
    if IGNORAR.search(os.path.basename(caminho)):
        continue
    try:
        raw = open(caminho, "rb").read()
        blob, fim_perfil = acha_player_data(raw)
        if blob is None: continue
        skills = acha_skills(blob)
        if not skills: continue
        base = os.path.basename(caminho)
        m = re.match(r"(?:Steam|Xbox)_(\d+)_(.+)\.fch$", base)
        plataforma, steamid, slug = ("Steam", m.group(1), m.group(2)) if m else ("?", None, base[:-4])
        nome = acha_nome(raw, fim_perfil) or slug

        brutos.append((nome, slug, plataforma, caminho, skills))
    except Exception:
        continue

MODS = nomes_de_mod({sid for _, _, _, _, sk in brutos for sid, _, _ in sk
                     if sid not in VANILLA})

for nome, slug, plataforma, caminho, skills in brutos:
    lista = []
    for sid, lvl, acc in skills:
        nm = VANILLA.get(sid) or MODS.get(sid)
        lista.append({
            "id": sid,
            "nome": PT_MOD.get(nm, nm) or f"Perícia de mod #{sid}",
            "nome_original": nm if nm in PT_MOD else None,
            "conhecida": nm is not None,
            "de_mod": sid not in VANILLA,
            "nivel": round(lvl, 2),
            "acumulado": round(acc, 2),
            "grupo": grupo_de(sid),
        })
    lista.sort(key=lambda s: (-s["nivel"], s["nome"]))
    total = round(sum(s["nivel"] for s in lista), 2)
    jogadores.append({
        "nome": nome,
        "slug": re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", nome)
                       .encode("ascii", "ignore").decode().lower()).strip("-") or "viking",
        "plataforma": plataforma,
        # o SteamID NAO vai para o JSON publico: identifica a pessoa e a
        # interface nao precisa dele. Fica so o dominio (Steam/Xbox).
        "total_niveis": total,
        "pericias_com_nivel": sum(1 for s in lista if s["nivel"] > 0),
        "maior": lista[0] if lista else None,
        "pericias": lista,
        "atualizado": datetime.fromtimestamp(os.path.getmtime(caminho), TZ).isoformat(timespec="seconds"),
    })

jogadores.sort(key=lambda j: -j["total_niveis"])
for i, j in enumerate(jogadores, 1): j["posicao"] = i

dados = {
    "gerado_em": datetime.now(TZ).isoformat(timespec="seconds"),
    "total_vikings": len(jogadores),
    "jogadores": jogadores,
}
os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(SAIDA))
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
os.chmod(tmp, 0o644); os.replace(tmp, SAIDA)
print(f"{len(jogadores)} viking(s) em {SAIDA}")
