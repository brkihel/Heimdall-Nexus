"""Jarl › Modpack: preview from Hexium, then write and publish only the verified version."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'servicos/painel'))
import executor  # noqa: E402

PACK = 'GenesisMods/GenesisHeimModPack'
API = 'https://valheim.hexium.gg/api/experimental/package/'


def hexium(version, deps):
    pages = {API + 'GenesisMods/GenesisHeimModPack/': {
        'package_url': 'https://valheim.hexium.gg/mods/GenesisMods/GenesisHeimModPack',
        'latest': {'version_number': version, 'dependencies': deps}}}
    for dep in deps:
        owner, name, number = dep.rsplit('-', 2)[0], dep.rsplit('-', 2)[1], dep.rsplit('-', 2)[2]
        pages[API + f'{owner}/{name}/'] = {'name': name, 'owner': owner,
                                            'latest': {'description': f'{name} in English'}}
    return pages.__getitem__


@pytest.fixture
def site(tmp_path, monkeypatch):
    web = ROOT / 'site/web'
    (tmp_path / 'sync_modpack.py').write_text((web / 'sync_modpack.py').read_text())
    (tmp_path / 'mods.json').write_text(json.dumps({
        'modpack': 'https://valheim.hexium.gg/mods/GenesisMods/GenesisHeimModPack', 'versao_pack': '1.0.0',
        'total': 2, 'mods': [{'pacote': 'A-Old', 'nome': 'Old', 'versao': '1.0.0'},
                             {'pacote': 'A-Kept', 'nome': 'Kept', 'versao': '1.0.0'}]}))
    (tmp_path / 'descricoes-pt.json').write_text(json.dumps({'A-Kept': 'Mantido'}))
    monkeypatch.setattr(executor, 'SITE_DIR', tmp_path)
    monkeypatch.setattr(executor, 'guarda_copia', lambda path: None)
    monkeypatch.setattr(executor, '_write_as_owner', lambda path, text: path.write_text(text))
    monkeypatch.setattr(executor, '_new_site_file', lambda path, data: path.write_bytes(data))
    published = []
    monkeypatch.setattr(executor, '_publish', lambda targets: published.append(targets) or [])
    fetch = hexium('2.0.0', ['A-Kept-1.1.0', 'A-New-0.1.0'])
    module = executor._modpack_module()
    original = module.build_list
    monkeypatch.setattr(executor, '_modpack_module', lambda: module)
    monkeypatch.setattr(module, 'build_list', lambda raw, overrides: original(raw, overrides, fetch))
    return tmp_path, published


def test_state_finds_the_package_from_the_published_list(site):
    assert executor.v_site_modpack({})['package'] == PACK


def test_preview_lists_changes_without_writing(site):
    path, published = site
    before = (path / 'mods.json').read_text()
    preview = executor.v_site_modpack_verificar({})
    assert preview['novo']['versao'] == '2.0.0'
    assert [m['pacote'] for m in preview['novos']] == ['A-New']
    assert [m['pacote'] for m in preview['removidos']] == ['A-Old']
    assert preview['alterados'] == [{'pacote': 'A-Kept', 'nome': 'Kept', 'de': '1.0.0', 'para': '1.1.0'}]
    assert [m['pacote'] for m in preview['sem_descricao']] == ['A-New']
    assert (path / 'mods.json').read_text() == before and not published


def test_apply_writes_verified_version_and_keeps_new_descriptions(site):
    path, published = site
    result = executor.v_site_modpack_aplicar({'versao': '2.0.0', 'descricoes': {'A-New': ' Novo\x07  mod '}})
    assert result['atual']['versao'] == '2.0.0' and published == [['mods']]
    mods = {m['pacote']: m for m in json.loads((path / 'mods.json').read_text())['mods']}
    assert mods['A-New']['descricao'] == 'Novo mod' and mods['A-Kept']['descricao'] == 'Mantido'
    assert json.loads((path / 'descricoes-pt.json').read_text()) == {'A-Kept': 'Mantido', 'A-New': 'Novo mod'}
    assert json.loads((path / 'modpack.json').read_text()) == {'package': PACK}


def test_apply_refuses_a_version_that_changed_or_bad_input(site):
    path, published = site
    for bad in ({'versao': '1.9.9'}, {'versao': '2.0.0', 'package': '../x'},
                {'versao': '2.0.0', 'descricoes': {'A-New': 'x' * 601}},
                {'versao': '2.0.0', 'descricoes': {'bad key': 'x'}}):
        with pytest.raises(executor.Recusa):
            executor.v_site_modpack_aplicar(bad)
    assert json.loads((path / 'mods.json').read_text())['versao_pack'] == '1.0.0' and not published


def test_failed_publish_restores_the_previous_files(site, monkeypatch):
    path, _ = site
    before = (path / 'mods.json').read_text()
    def fail(targets):
        raise executor.Recusa('a publicação falhou')
    monkeypatch.setattr(executor, '_publish', fail)
    with pytest.raises(executor.Recusa):
        executor.v_site_modpack_aplicar({'versao': '2.0.0', 'descricoes': {'A-New': 'Novo'}})
    assert (path / 'mods.json').read_text() == before
    assert not (path / 'modpack.json').exists()
    assert json.loads((path / 'descricoes-pt.json').read_text()) == {'A-Kept': 'Mantido'}
