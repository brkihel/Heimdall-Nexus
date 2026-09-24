#!/usr/bin/env python3
"""Fetch a Thunderstore-compatible modpack from Hexium into a reviewable JSON list.

The modpack package is configurable per server. Descriptions in the optional
overrides file remain editorial copy and take precedence over store text.
Nothing is written unless --apply is passed.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path

API = "https://valheim.hexium.gg/api/experimental/package/"
UA = {"User-Agent": "heimdall-site-modpack-sync/1.0"}
VERSION = re.compile(r"\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.-]+)?$")


class SyncError(RuntimeError):
    pass


def get_json(url: str, timeout: int = 25) -> dict:
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def parse_dependency(value: str) -> tuple[str, str, str]:
    """Return package id, owner and pinned version from Owner-Name-Version."""
    owner_and_name, sep, version = value.rpartition("-")
    if not sep or not VERSION.fullmatch(version) or "-" not in owner_and_name:
        raise SyncError(f"Dependência Hexium fora do formato esperado: {value}")
    owner, name = owner_and_name.split("-", 1)
    if not owner or not name:
        raise SyncError(f"Dependência Hexium incompleta: {value}")
    return f"{owner}-{name}", owner, version


def package_slug(raw: str) -> tuple[str, str]:
    parts = raw.strip("/").split("/")
    if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", x) for x in parts):
        raise SyncError("O pacote deve estar no formato autor/nome.")
    return parts[0], parts[1]


def web_url(raw: str, fallback: str = "") -> str:
    parsed = urlparse(raw or "")
    return raw if parsed.scheme == "https" and parsed.netloc and not parsed.username else fallback


def read_package(raw: str, fetch=get_json) -> dict:
    owner, name = package_slug(raw)
    url = API + f"{owner}/{name}/"
    try:
        data = fetch(url)
        latest = data["latest"]
        deps = latest["dependencies"]
        if not isinstance(deps, list):
            raise TypeError("dependencies não é lista")
        return {"url": data.get("package_url") or f"https://valheim.hexium.gg/mods/{owner}/{name}",
                "version": latest["version_number"], "dependencies": deps}
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as exc:
        raise SyncError(f"Não consegui ler o modpack {raw} no Hexium: {exc}") from exc


def package_metadata(package_id: str, owner: str, pinned: str, fetch=get_json) -> dict:
    name = package_id.split("-", 1)[1]
    try:
        data = fetch(API + f"{owner}/{name}/")
        version = data.get("latest") or {}
        package_url = web_url(data.get("package_url"), f"https://valheim.hexium.gg/mods/{owner}/{name}")
        return {"pacote": package_id, "nome": data.get("name") or name,
                "autor": data.get("owner") or owner, "versao": pinned,
                "descricao": str(version.get("description") or "").strip(),
                "original": str(version.get("description") or "").strip(),
                "icone": web_url(version.get("icon")), "url": package_url,
                "loja": "hexium"}
    except Exception as exc:  # one missing metadata entry must not discard the pack
        return {"pacote": package_id, "nome": name, "autor": owner, "versao": pinned,
                "descricao": "", "original": "", "icone": "",
                "url": f"https://valheim.hexium.gg/mods/{owner}/{name}",
                "loja": "hexium", "metadata_error": str(exc)[:180]}


def build_list(raw: str, overrides: dict, fetch=get_json) -> dict:
    pack = read_package(raw, fetch)
    parsed = [parse_dependency(dep) for dep in pack["dependencies"]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        mods = list(pool.map(lambda row: package_metadata(*row, fetch=fetch), parsed))
    mods = [m for m in mods if m["pacote"] != raw.replace("/", "-")]
    for mod in mods:
        editorial = overrides.get(mod["pacote"])
        if editorial is not None:
            mod["descricao"] = str(editorial).strip()
            mod["traduzida"] = True
        else:
            mod["traduzida"] = False
        mod.pop("metadata_error", None)
    mods.sort(key=lambda m: m["nome"].casefold())
    return {"modpack": web_url(pack["url"]), "modpack_owner": package_slug(raw)[0],
            "versao_pack": pack["version"],
            "atualizado_em": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "total": len(mods), "mods": mods}


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def changes(old: dict, new: dict) -> tuple[list[str], list[str], list[str]]:
    before = {m["pacote"]: m for m in old.get("mods", [])}
    after = {m["pacote"]: m for m in new.get("mods", [])}
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    changed = sorted(k for k in before.keys() & after.keys()
                     if before[k].get("versao") != after[k].get("versao"))
    return added, removed, changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", help="Hexium modpack no formato autor/nome")
    parser.add_argument("--config", type=Path, help="JSON da instância com package e descrições")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("mods.json"))
    parser.add_argument("--descriptions", type=Path, help="JSON: pacote -> descrição revisada")
    parser.add_argument("--apply", action="store_true", help="grava mods.json; sem esta opção só mostra a prévia")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    package = args.package or config.get("package")
    if not package:
        parser.error("informe --package ou use um --config que contenha package")
    descriptions = args.descriptions
    if descriptions is None and config.get("description_overrides"):
        descriptions = Path(config["description_overrides"])
        if not descriptions.is_absolute() and args.config:
            descriptions = args.config.parent / descriptions
    overrides = json.loads(descriptions.read_text(encoding="utf-8")) if descriptions else {}
    try:
        new = build_list(package, overrides)
    except SyncError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    old = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {}
    added, removed, changed = changes(old, new)
    print(f"Modpack {new['versao_pack']}: {new['total']} mods")
    print(f"Novos: {', '.join(added) if added else 'nenhum'}")
    print(f"Removidos: {', '.join(removed) if removed else 'nenhum'}")
    print(f"Versão alterada: {', '.join(changed) if changed else 'nenhuma'}")
    if not args.apply:
        print("Prévia apenas. Para gravar, repita com --apply.")
        return 0
    atomic_json(args.output, new)
    print(f"Atualizado: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
