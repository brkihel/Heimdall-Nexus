#!/usr/bin/python3
"""Gera o feed público de status a partir do estado real do servidor."""
import json, socket, struct, subprocess, re, os, glob, sys, tempfile, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sistema import hostos  # noqa: E402

TZ = ZoneInfo(os.environ.get("HEIMDALL_TIMEZONE", "America/Sao_Paulo"))
VALHEIM_DIR = str(hostos.env_path("HEIMDALL_VALHEIM_DIR"))
SERVER_NAME = os.environ.get("HEIMDALL_SERVER_NAME", "Valheim Server")
SERVER_ADDRESS = os.environ.get("HEIMDALL_SERVER_ADDRESS", "play.example.org")
SERVER_IP = os.environ.get("HEIMDALL_SERVER_IP", "")
SERVER_PORT = os.environ.get("HEIMDALL_SERVER_PORT", "2456")
WORLD_NAME = os.environ.get("HEIMDALL_WORLD_NAME", "Valheim")
WEB_DIR = str(hostos.env_path("HEIMDALL_WEB_DIR"))
CONFIG_DIR = os.path.join(VALHEIM_DIR, "config/BepInEx")
OUT = os.environ.get("HEIMDALL_STATUS_FILE", os.path.join(WEB_DIR, "api/status.json"))
CFG = os.environ.get("HEIMDALL_STATUS_RESTART_CFG", os.path.join(CONFIG_DIR, "org.tristan.serverrestart.cfg"))
ENV = os.environ.get("HEIMDALL_SERVER_ENV", os.path.join(VALHEIM_DIR, "server.env"))
try:
    with open(ENV, encoding='utf-8') as settings_file:
        for setting in settings_file:
            if '=' not in setting or setting.lstrip().startswith('#'):
                continue
            key, raw = setting.rstrip('\n').split('=', 1)
            try:
                value = json.loads(raw)
            except (ValueError, TypeError):
                value = raw.strip('"\'')
            if key == 'VH_NAME': SERVER_NAME = str(value)
            elif key == 'VH_WORLD': WORLD_NAME = str(value)
            elif key == 'VH_PORT' and str(value).isdigit(): SERVER_PORT = str(value)
except OSError:
    pass
try:
    with open(os.path.join(VALHEIM_DIR, 'server-profile.json'), encoding='utf-8') as profile_file:
        SERVER_DESCRIPTION = str(json.load(profile_file).get('description', ''))[:500]
except (OSError, ValueError, TypeError):
    SERVER_DESCRIPTION = ''
MUNDOS = os.environ.get("HEIMDALL_WORLD_DIR",
                        os.path.join(VALHEIM_DIR, "saves/worlds_local", WORLD_NAME))

ZWS = os.environ.get("HEIMDALL_STATUS_ZWS_CFG", os.path.join(CONFIG_DIR, "ZenDragon.ZenWorldSettings.cfg"))
MDN = os.environ.get("HEIMDALL_STATUS_MRD_CFG", os.path.join(CONFIG_DIR, "genesisproj.mrdaynight.cfg"))
SEA = os.environ.get("HEIMDALL_STATUS_SEASON_CFG", os.path.join(CONFIG_DIR, "RustyMods.Seasonality.cfg"))
GIS = os.environ.get("HEIMDALL_STATUS_STACKS_CFG", os.path.join(CONFIG_DIR, "Genesis.zzzGenesisItemStacks.cfg"))
DIA_VANILLA = 1800.0      # um dia de Valheim dura 30 min reais

# Constantes conferidas no IL do assembly_valheim (1.0.14), nao chutadas:
#   EnvMan.GetCurrentDay() = (int)(m_totalSeconds / m_dayLengthSec)   <- SEM +1
#   EnvMan.RescaleDayFraction remapeia a fracao crua 0.15..0.85 para 0.25..0.75,
#   e CalculateDay/CalculateNight comparam contra 0.25 e 0.75 — por isso o
#   vanilla e sempre 70% dia e 30% noite, e por isso amanhece em 0.15.
FRACAO_MANHA_VANILLA = 0.15

def hora_do_dia(frac, amanhecer):
    """Converte a fracao crua do ciclo em hora de relogio, 0..24.

    Usa a MESMA conta do jogo (EnvMan.RescaleDayFraction): a faixa de luz
    [amanhecer, anoitecer] e remapeada para [0.25, 0.75], que em 24 horas e
    exatamente 06:00 e 18:00. A noite fica nas pontas, em torno da meia-noite.

    A conta anterior — (frac - amanhecer) * 24 + 6 — supunha proporcao fixa
    entre dia e noite. Com o MrDayNight mudando essa proporcao, ela punha o
    anoitecer depois da meia-noite."""
    baixo = min(max(amanhecer, 0.001), 0.499)
    alto = 1.0 - baixo
    if frac < baixo:
        r = frac / baixo * 0.25
    elif frac > alto:
        r = 0.75 + (frac - alto) / baixo * 0.25
    else:
        r = 0.25 + (frac - baixo) / (alto - baixo) * 0.5
    return (r * 24.0) % 24.0

def _num(caminho, chave):
    """Le um numero de uma chave de arquivo .cfg do BepInEx."""
    try:
        txt = open(caminho, encoding="utf-8", errors="replace").read()
        m = re.search(r'^' + re.escape(chave) + r'\s*=\s*([\d.]+)', txt, re.M)
        if m: return float(m.group(1))
    except Exception:
        pass
    return None

def _ligado(caminho, chave):
    try:
        txt = open(caminho, encoding="utf-8", errors="replace").read()
        m = re.search(r'^' + re.escape(chave) + r'\s*=\s*(\w+)', txt, re.M)
        if m: return m.group(1).strip().lower() == "true"
    except Exception:
        pass
    return False

def ciclo_do_dia():
    """Devolve (duracao do ciclo em segundos, fracao em que amanhece, quem manda).

    Dois mods podem controlar isto. O MrDayNight escreve m_dayLengthSec por
    ultimo (SoftDependency + HarmonyPriority.Last), entao ele ganha quando
    esta ligado — e so ele muda a PROPORCAO entre dia e noite, deslocando o
    amanhecer para longe do 0.15 do jogo base."""
    if os.path.exists(MDN) and _ligado(MDN, "Enabled"):
        dia = _num(MDN, "DayLength")
        noite = _num(MDN, "NightLength")
        if dia and noite and dia + noite > 0:
            total = dia + noite
            # a noite fica centrada na virada do ciclo: metade no fim, metade no comeco
            return total, (noite / total) / 2.0, "MrDayNight"
    v = _num(ZWS, "Day Length Seconds")
    if v and v > 0:
        return v, FRACAO_MANHA_VANILLA, "ZenWorldSettings"
    return DIA_VANILLA, FRACAO_MANHA_VANILLA, "vanilla"
ESTACOES = [("Spring", "Primavera"), ("Summer", "Verao"),
            ("Fall", "Outono"), ("Winter", "Inverno")]
# cada modificador: rotulo, se e multiplicador (senao e soma), e se subir e bom
MODIFS = [
    ("Carry Weight",         "Capacidade de carga", False, True),
    ("Health Regeneration",  "Regeneracao de vida", True,  True),
    ("Stamina Regeneration", "Regeneracao de estamina", True, True),
    ("Eitr Regeneration",    "Regeneracao de eitr", True,  True),
    ("Damage",               "Dano causado",        True,  True),
    ("Speed",                "Velocidade",          True,  True),
    ("Raise Skill",          "Ganho de pericia",    True,  True),
]

def _secoes(texto):
    """Fatia um .cfg do BepInEx em secoes, respeitando o proximo cabecalho."""
    marcas = [(m.start(), m.group(1)) for m in re.finditer(r"^\[([^\]]+)\]", texto, re.M)]
    saida = {}
    for i, (pos, nome) in enumerate(marcas):
        fim = marcas[i + 1][0] if i + 1 < len(marcas) else len(texto)
        saida[nome] = texto[pos:fim]
    return saida

# Display names for the categories zzzGenesisItemStacks knows. The list itself is read
# from the .cfg (every "<X> Stack Multiplier"), so a category added to the mod shows up
# on the site even before it gets a name here.
NOMES_CATEGORIA = {
    "Ore": "Minério", "Wood": "Madeira", "Material": "Materiais", "Food": "Comida",
    "Ammunition": "Munição", "Valuable": "Valiosos", "Stone": "Pedra e gemas",
    "Seed": "Sementes", "Crop": "Colheita", "Potion": "Poções", "Trophy": "Troféus",
    "Tool": "Ferramentas", "Weapon": "Armas", "Armor": "Armaduras", "Jewelry": "Joias",
}

def editados():
    """Items the admin typed a value for in item_stack.cfg / item_weight.cfg.

    Each entry carries its vanilla value in '# Default value:'; a different value means it
    was set on purpose, and the mod applies it over any multiplier."""
    base = os.path.join(os.path.dirname(GIS), "GenesisItemStacks")
    out = {}
    for arquivo, chave, campo in (("item_stack.cfg", "MaxStack", "pilha"),
                                  ("item_weight.cfg", "Weight", "peso")):
        try:
            texto = open(os.path.join(base, arquivo), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for bloco in re.split(r"^\[Item\.", texto, flags=re.M)[1:]:
            nome = bloco.split("]", 1)[0]
            padrao = re.search(r"^# Default value:\s*([\d.]+)", bloco, re.M)
            valor = re.search(r"^" + chave + r"\s*=\s*([\d.]+)", bloco, re.M)
            if padrao and valor and abs(float(padrao.group(1)) - float(valor.group(1))) > 1e-4:
                out.setdefault(nome, {})[campo] = {"vanilla": float(padrao.group(1)),
                                                   "aqui": float(valor.group(1))}
    return out

def itens():
    """Pilhas e pesos, lidos do zzzGenesisItemStacks.

    Ele tem tres modos, nesta ordem de prioridade: global, por categoria e
    por item. Publicar qual esta valendo evita o site afirmar um numero que
    nao e mais o que o servidor aplica."""
    try:
        txt = open(GIS, encoding="utf-8", errors="replace").read()
    except Exception:
        return None
    secs = _secoes(txt)
    def num(bloco, chave):
        m = re.search(r"^" + re.escape(chave) + r"\s*=\s*([\d.]+)", bloco, re.M)
        return float(m.group(1)) if m else None
    def liga(bloco, chave):
        m = re.search(r"^" + re.escape(chave) + r"\s*=\s*(\w+)", bloco, re.M)
        return bool(m) and m.group(1).strip().lower() == "true"

    geral = secs.get("2 - General", "")
    if not liga(geral, "Mod Enabled"):
        return {"ativo": False}

    glob = secs.get("3 - Global Multipliers", "")
    cats = secs.get("4 - Category Multipliers", "")
    pesos = secs.get("5 - Category Weight Multipliers", "")

    usa_global_pilha = liga(glob, "Use Global Stack Multiplier")
    usa_global_peso  = liga(glob, "Use Global Weight Multiplier")
    usa_cat = liga(cats, "Use Category Multipliers")

    modo = "global" if (usa_global_pilha or usa_global_peso) else ("categorias" if usa_cat else "por item")

    lista = []
    if modo == "categorias":
        chaves = re.findall(r"^(\w+) Stack Multiplier\s*=", cats, re.M)
        for chave in chaves:
            pilha = num(cats, f"{chave} Stack Multiplier")
            peso  = num(pesos, f"{chave} Weight Multiplier")
            lista.append({"chave": chave, "nome": NOMES_CATEGORIA.get(chave, chave),
                          "pilha": pilha if pilha is not None else 1.0,
                          "peso":  peso  if peso  is not None else 1.0})

    return {
        "ativo": True,
        "modo": modo,
        "afeta_mods": liga(geral, "Affect Modded Items"),
        "global": {
            "pilha": num(glob, "Global Stack Multiplier"),
            "peso":  num(glob, "Global Weight Multiplier"),
            "pilha_ativa": usa_global_pilha,
            "peso_ativo":  usa_global_peso,
        },
        "categorias": lista,
        # hand-edited items beat every multiplier in the mod (see its Priority comment)
        "editados": editados(),
        # tudo que nao cai numa categoria fica vanilla (`_ => 1.0f` no mod)
        "resto": {"pilha": 1.0, "peso": 1.0},
    }

def estacoes(DIA_SEG):
    """Estacao atual e o que cada uma faz, lidos do Seasonality.

    O mod grava a estacao de volta no proprio .cfg quando ela vira (SetNextSeason
    escreve no ConfigEntry), entao ler o arquivo basta — nao precisa de plugin."""
    try:
        txt = open(SEA, encoding="utf-8", errors="replace").read()
    except Exception:
        return None
    secs = _secoes(txt)
    def val(bloco, chave, padrao):
        m = re.search(r"^" + re.escape(chave) + r"\s*=\s*(\S+)", bloco, re.M)
        try: return float(m.group(1)) if m else padrao
        except ValueError: return padrao

    geral = secs.get("1 - Settings", "")
    m = re.search(r"^Season\s*=\s*(\w+)", geral, re.M)
    atual = m.group(1) if m else None
    ligado = bool(re.search(r"^Modifiers Enabled\s*=\s*On", geral, re.M))

    # duracao: {"x":dias,"y":horas,"z":minutos} de tempo REAL (o mod nunca olha
    # o tamanho do dia), entao quantos dias de jogo cabem depende do ciclo
    dur_seg = None
    bloco0 = secs.get(atual or "", "")
    d = re.search(r'^In-Game Duration\s*=\s*\{"x":([\d.]+),"y":([\d.]+),"z":([\d.]+)\}', bloco0, re.M)
    if d:
        dur_seg = float(d.group(1)) * 86400 + float(d.group(2)) * 3600 + float(d.group(3)) * 60

    lista = []
    for chave, nome_pt in ESTACOES:
        bloco = secs.get(chave, "")
        if not bloco: continue
        efeitos = []
        for cfg, rotulo, mult, _ in MODIFS:
            v = val(bloco, cfg, 1.0 if mult else 0.0)
            neutro = 1.0 if mult else 0.0
            if abs(v - neutro) < 1e-9: continue
            efeitos.append({
                "nome": rotulo,
                "valor": v,
                "tipo": "multiplicador" if mult else "soma",
                "texto": (f"{(v-1)*100:+.0f}%" if mult else f"{v:+.0f}"),
                "bom": v > neutro,
            })
        lista.append({"chave": chave, "nome": nome_pt,
                      "atual": chave == atual, "efeitos": efeitos})
    return {
        "atual": atual,
        "modificadores_ativos": ligado,
        "duracao_seg": int(dur_seg) if dur_seg else None,
        "duracao_dias_de_jogo": round(dur_seg / DIA_SEG, 2) if dur_seg and DIA_SEG else None,
        "lista": lista,
    }

# multiplicadores do modificador de mundo "resources"
RATES = {"muchless":"0,5x", "less":"0,75x", "default":"1x", "more":"1,5x", "muchmore":"2x"}

def tempo_de_jogo(servico_ativo, inicio_servico, DIA_SEG, FRACAO_MANHA, QUEM,
                  jogadores_online=0):
    """Le o netTime do mundo salvo e, se o mundo estiver correndo, extrapola.

    O relogio do mundo NAO corre com o servidor: ele corre enquanto ha alguem
    conectado. Com o salao vazio o netTime fica exatamente onde foi gravado —
    medido aqui: 8h de servidor no ar, zero jogadores, netTime +0.0s.

    Antes extrapolavamos sempre que o servico estava ativo, e o relogio do site
    andava para a frente por ate 20 minutos e VOLTAVA ATRAS no save seguinte.
    Agora so extrapolamos com jogador online. Sem ninguem dentro o site
    publica o valor gravado, que e a verdade: nao ha o que extrapolar."""
    try:
        arquivos = sorted(glob.glob(os.path.join(MUNDOS, "_main.*.db2")))
        if not arquivos: return None
        caminho = arquivos[-1]
        with open(caminho, "rb") as fh: cab = fh.read(16)
        if len(cab) < 12: return None
        net, = struct.unpack_from("<d", cab, 4)
        if not (0 <= net < 10**9): return None
        base = os.path.getmtime(caminho)
        atraso_save = max(0.0, datetime.now(timezone.utc).timestamp() - base)
        gravado = net
        correndo = bool(servico_ativo and jogadores_online is not None and jogadores_online > 0)
        if correndo:
            if inicio_servico: base = max(base, inicio_servico.timestamp())
            net += max(0.0, datetime.now(timezone.utc).timestamp() - base)
        dia = int(net // DIA_SEG)                    # igual ao GetCurrentDay do jogo
        frac = (net % DIA_SEG) / DIA_SEG
        # ancora o relogio no amanhecer: fracao 0.15 == 06:00
        h24 = hora_do_dia(frac, FRACAO_MANHA)
        hh, mm = int(h24), int(round((h24 % 1) * 60))
        if mm == 60: hh, mm = (hh + 1) % 24, 0
        if   hh < 5:  periodo = "madrugada"
        elif hh < 7:  periodo = "amanhecer"
        elif hh < 12: periodo = "manha"
        elif hh < 14: periodo = "meio-dia"
        elif hh < 18: periodo = "tarde"
        elif hh < 20: periodo = "entardecer"
        else:         periodo = "noite"
        return {"dia": dia, "hora": f"{hh:02d}:{mm:02d}",
                "fracao": round(frac, 4), "periodo": periodo,
                "segundos_mundo": int(net),
                # o numero do dia encolhe quando a duracao do ciclo aumenta
                # (o jogo faz dia = tempoTotal / duracaoDoDia). As horas de mundo
                # nao encolhem, entao servem melhor para medir a jornada.
                "horas_de_mundo": round(net / 3600.0, 1),
                "duracao_dia_seg": int(DIA_SEG),
                "duracao_dia_vanilla": DIA_SEG == DIA_VANILLA,
                "ciclo_controlado_por": QUEM,
                "fracao_manha": round(FRACAO_MANHA, 6),
                "hora_anoitecer": round(1.0 - FRACAO_MANHA, 6),
                # ha quanto tempo o mundo foi gravado: dormir no jogo salta o
                # relogio, e o site so enxerga o salto no proximo save
                "salvo_ha_seg": int(atraso_save),
                # o relogio do mundo so anda com gente dentro
                "correndo": correndo,
                "segundos_gravados": int(gravado)}
    except Exception:
        return None

def taxa_recursos():
    try:
        txt = open(ENV, encoding="utf-8", errors="replace").read()
        m = re.search(r'^VH_RESOURCES=(\S+)', txt, re.M)
        chave = (m.group(1).strip() if m else "default").lower()
        return {"recursos": RATES.get(chave, chave), "modificador": chave}
    except Exception:
        return {"recursos": "1x", "modificador": "default"}

def a2s(host="127.0.0.1", port=2457, timeout=4):
    """Consulta A2S_INFO. Devolve dict ou None."""
    req = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(timeout)
        s.sendto(req, (host, port)); d, _ = s.recvfrom(4096)
        if d[4:5] == b'A':
            s.sendto(req + d[5:9], (host, port)); d, _ = s.recvfrom(4096)
        p = d[6:].split(b'\x00')
        tail = b'\x00'.join(p[4:])
        return {"nome": p[0].decode('utf8','replace'),
                "mundo": p[1].decode('utf8','replace'),
                "online": tail[2], "maximo": tail[3],
                "protegido_por_senha": bool(tail[6] == 1)}
    except Exception:
        return None
    finally:
        try: s.close()
        except Exception: pass

GAME_SERVICE = os.environ.get('HEIMDALL_GAME_SERVICE') or 'heimdall-valheim'


def pronto_no_journal():
    """Confirma a prontidão da execução atual quando a consulta A2S não responde.

    O servidor pode aceitar jogadores mesmo sem responder à consulta UDP de
    status. Só a execução atual conta: um início anterior não marca o atual
    como pronto. O log só é consultado quando o processo está ativo e A2S falhou.
    """
    try:
        return bool(hostos.service_logged_since_start(GAME_SERVICE, "Game server connected"))
    except Exception:
        return False

def proximo_reinicio():
    """Le o agendamento (UTC) do ServerRestart e devolve o proximo horario."""
    try:
        txt = open(CFG, encoding='utf-8', errors='replace').read()
        m = re.search(r'^Schedule \(utc\) = (.+)$', txt, re.M)
        if not m: return None, []
        horarios = [h.strip() for h in m.group(1).split(',') if h.strip()]
        agora = datetime.now(timezone.utc)
        cand = []
        for h in horarios:
            hh, mm, ss = (list(map(int, h.split(':'))) + [0,0,0])[:3]
            for dia in (0, 1):
                t = (agora + timedelta(days=dia)).replace(hour=hh, minute=mm, second=ss, microsecond=0)
                if t > agora: cand.append(t)
        locais = sorted({datetime.strptime(h, "%H:%M:%S").replace(
                            year=agora.year, month=agora.month, day=agora.day,
                            tzinfo=timezone.utc).astimezone(TZ).strftime("%H:%M")
                         for h in horarios})
        return (min(cand).astimezone(TZ) if cand else None), locais
    except Exception:
        return None, []

DIA_SEG, FRACAO_MANHA, QUEM_MANDA = ciclo_do_dia()
info   = a2s(port=int(SERVER_PORT) + 1)
ativo  = hostos.service_is_active(GAME_SERVICE)
pronto = ativo and (bool(info) or pronto_no_journal())
inicio = None
# The host layer measures uptime without the timezone traps of formatted times.
elapsed = hostos.service_active_seconds(GAME_SERVICE) if ativo else None
if elapsed is not None:
    inicio = datetime.now(timezone.utc) - timedelta(seconds=elapsed)

agora = datetime.now(TZ)
prox, horarios_locais = proximo_reinicio()

dados = {
    "gerado_em": agora.isoformat(timespec="seconds"),
    "online": pronto,
    "status_consulta": "a2s" if info else "journal" if pronto else "indisponivel",
    "servidor": {
        "nome": (info or {}).get("nome", SERVER_NAME),
        "descricao": SERVER_DESCRIPTION,
        "mundo": (info or {}).get("mundo", WORLD_NAME),
        "endereco": f"{SERVER_ADDRESS}:{SERVER_PORT}",
        "endereco_ip": f"{SERVER_IP}:{SERVER_PORT}" if SERVER_IP else None,
        "senha": None if not info else ("sim" if info["protegido_por_senha"] else "nao"),
    },
    "jogadores": {"online": info.get("online") if info else None,
                  "maximo": (info or {}).get("maximo", 10)},
    "uptime": {
        "desde": inicio.isoformat(timespec="seconds") if inicio else None,
        "segundos": int((agora - inicio).total_seconds()) if inicio else None,
    },
    "tempo_de_jogo": tempo_de_jogo(ativo, inicio, DIA_SEG, FRACAO_MANHA,
                                   QUEM_MANDA, info.get("online") if info else None),
    "estacoes": estacoes(DIA_SEG),
    "itens": itens(),
    "taxas": taxa_recursos(),
    "proximo_reinicio": {
        "em": prox.isoformat(timespec="seconds") if prox else None,
        "segundos_restantes": int((prox - agora).total_seconds()) if prox else None,
        "horarios_diarios": horarios_locais,
        "fuso": os.environ.get("HEIMDALL_TIMEZONE", "America/Sao_Paulo"),
    },
}

def publica_mods_instalados():
    """Espelha em /api o que esta REALMENTE instalado na release ativa.

    O mods.lock.json fica na instalação do servidor; o caminho pode ser
    substituído por HEIMDALL_MODS_LOCK para instalações com outra estrutura.
    Quem roda este script ja tem a chave; servicos sem privilegio leem o
    resultado pela mesma /api que o site ja serve, sem afrouxar permissao
    de diretorio.
    """
    destino = os.path.join(os.path.dirname(OUT), "mods-instalados.json")
    try:
        with open(os.environ.get("HEIMDALL_MODS_LOCK",
                                 os.path.join(VALHEIM_DIR, "current/mods.lock.json")),
                  encoding="utf-8") as f:
            lock = json.load(f)
    except (OSError, ValueError):
        return
    magro = {
        "gerado_em": agora.isoformat(timespec="seconds"),
        "jogo": lock.get("game_version"),
        "build": lock.get("game_build"),
        "bepinex": lock.get("bepinex"),
        "pacotes": {nome: (p.get("version") or "?")
                    for nome, p in sorted(lock.get("packages", {}).items())},
    }
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(destino))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(magro, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o644); os.replace(tmp, destino)


os.makedirs(os.path.dirname(OUT), exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT))
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(dados, f, ensure_ascii=False, indent=1)
os.chmod(tmp, 0o644); os.replace(tmp, OUT)
publica_mods_instalados()
print(json.dumps(dados, ensure_ascii=False))
