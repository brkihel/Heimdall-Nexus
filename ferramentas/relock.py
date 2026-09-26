#!/usr/bin/python3
"""Reconstroi o mods.lock.json a partir do que esta REALMENTE instalado na release ativa.

Usa como fonte da verdade o disco (pastas de plugin/patcher + manifest.json de cada
pacote), e nao um registro paralelo que pode ficar defasado quando mods sao
instalados a mao.
"""
import json, hashlib, re, sys, datetime, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'servicos' / 'painel'))
import hostos  # noqa: E402

VALHEIM = hostos.env_path('HEIMDALL_VALHEIM_DIR')
RAIZ = (VALHEIM / "current").resolve(strict=True)
PLUGINS  = RAIZ / "BepInEx/plugins"
PATCHERS = RAIZ / "BepInEx/patchers"
DOCS     = RAIZ / "package-docs"
MANIFEST = RAIZ / "steamapps/appmanifest_896660.acf"
LOG      = Path(os.environ.get("HEIMDALL_GAME_LOG", str(VALHEIM / "logs/valheim.log")))

def versoes_do_log():
    """Fallback: o BepInEx registra 'Loading [Nome Versao]' de tudo que carregou.
    Alguns pacotes vindos do Hexium nao trazem manifest.json."""
    out = {}
    try:
        txt = (RAIZ / "BepInEx/LogOutput.log").read_text(errors="replace")
    except Exception:
        return out
    # plugins: "Loading [Nome Versao]"
    # patchers: "Loaded N patcher method from [Nome Versao]" — outra frase, e o
    # nome ali usa ponto (BRKiHeL.BowsBeforeHoesCompat) enquanto a pasta usa hifen.
    for padrao in (r"Loading \[([^\]]+?) ([0-9][0-9.]*)\]",
                   r"patcher method from \[([^\]]+?) ([0-9][0-9.]*)\]"):
        for m in re.finditer(padrao, txt):
            chave = re.sub(r"[^a-z0-9]", "", m.group(1).lower())
            out.setdefault(chave, m.group(2).rstrip("."))
    return out

LOG_VERSOES = versoes_do_log()

def versao_por_log(nome_pacote):
    """Casa 'Autor-NomeDoPacote' com o nome exibido pelo BepInEx.
    Tenta o nome curto e o completo: patchers aparecem como 'Autor.Nome'."""
    for cand in (nome_pacote.split("-", 1)[-1], nome_pacote):
        v = LOG_VERSOES.get(re.sub(r"[^a-z0-9]", "", cand.lower()))
        if v: return v
    return None

def manifesto(nome):
    # A pasta do plugin vem PRIMEIRO: ela e o que esta rodando. O package-docs guarda
    # o manifest da instalacao e nem sempre e reescrito numa atualizacao, entao lido
    # primeiro ele devolve a versao velha de um mod que ja foi atualizado.
    for cand in (PLUGINS / nome / "manifest.json", PATCHERS / nome / "manifest.json",
                 DOCS / nome / "manifest.json"):
        if cand.is_file():
            try: return json.loads(cand.read_text(encoding="utf-8-sig"))
            except Exception: pass
    return None

def digest_dir(d):
    """sha256 do conteudo do pacote: soma ordenada dos arquivos, para detectar drift."""
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        h.update(f.relative_to(d).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()

def build_do_jogo():
    try:
        m = re.search(r'"buildid"\s+"(\d+)"', MANIFEST.read_text(errors="replace"))
        return m.group(1) if m else None
    except Exception: return None

def versao_do_jogo():
    for leitura in (
        lambda: LOG.read_text(errors="replace"),
        lambda: hostos.service_log_text(os.environ.get('HEIMDALL_GAME_SERVICE', 'heimdall-valheim'), 20000),
    ):
        try:
            # a ULTIMA ocorrencia: o journal guarda execucoes antigas, de antes
            # da atualizacao do jogo, e a primeira seria a versao errada.
            achados = re.findall(r"Valheim [Vv]ersion:?\s*(l-[0-9.]+)", leitura())
            if achados: return achados[-1]
        except Exception: continue
    return None

pacotes = {}
for base, tipo in ((PLUGINS, "plugin"), (PATCHERS, "patcher")):
    if not base.is_dir(): continue
    for d in sorted(base.iterdir()):
        if not d.is_dir(): continue
        nome = d.name
        man = manifesto(nome)
        entrada = pacotes.setdefault(nome, {"tipo": [], "version": None})
        if tipo not in entrada["tipo"]: entrada["tipo"].append(tipo)
        if man:
            entrada["version"] = man.get("version_number")
            entrada["deps"] = man.get("dependencies") or []
            if man.get("website_url"): entrada["site"] = man["website_url"]
        if not entrada.get("version"):
            v = versao_por_log(nome)
            if v:
                entrada["version"] = v
                entrada["origem_versao"] = "log do BepInEx (pacote sem manifest.json)"
        entrada["sha256_conteudo"] = digest_dir(d)
        entrada.setdefault("dlls", []).extend(
            sorted(p.name for p in d.rglob("*.dll")))

sem_versao = [n for n, v in pacotes.items() if not v.get("version")]
lock = {
    "game_version": versao_do_jogo(),
    "game_build": build_do_jogo(),
    "bepinex": None,
    "release": str(RAIZ),
    "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    "packages": {n: dict(sorted(v.items())) for n, v in sorted(pacotes.items())},
}
# BepInEx nao tem pasta em plugins/: le a versao do log
try:
    m = re.search(r"BepInExPack Valheim version (\S+)", Path(
        RAIZ / "BepInEx/LogOutput.log").read_text(errors="replace"))
    if m: lock["bepinex"] = f"denikson-BepInExPack_Valheim {m.group(1)}"
except Exception: pass

destino = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "mods.lock.json"
destino.write_text(json.dumps(lock, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"{len(pacotes)} pacotes -> {destino}")
print(f"  jogo: {lock['game_version']} (build {lock['game_build']})")
print(f"  bepinex: {lock['bepinex']}")
if sem_versao: print(f"  !! sem manifest.json (versao desconhecida): {sem_versao}")
