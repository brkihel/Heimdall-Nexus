"""A mod's dependencies: found before installing, shown to the admin, installed together."""
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'servicos/painel'))
import executor  # noqa: E402


def version(number, deps=None):
    entry = {'version_number': number, 'download_url': f'https://example.org/{number}.zip'}
    if deps is not None:
        entry['dependencies'] = deps
    return entry


CATALOG = [
    {'full_name': 'RustyMods-Seasonality', 'loja': 'hexium', 'package_url': 'https://valheim.hexium.gg/mods/RustyMods/Seasonality',
     'versions': [version('3.8.3', ['denikson-BepInExPack_Valheim-5.4.2350', 'ValheimModding-YamlDotNet-16.3.1'])]},
    {'full_name': 'ValheimModding-YamlDotNet', 'loja': 'hexium', 'package_url': 'https://valheim.hexium.gg/mods/ValheimModding/YamlDotNet',
     'versions': [version('16.3.2', []), version('16.3.1', [])]},
    {'full_name': 'Azumatt-Needs', 'loja': 'hexium', 'package_url': 'https://valheim.hexium.gg/mods/Azumatt/Needs',
     'versions': [version('1.0.0', ['ValheimModding-Jotunn-2.20.0', 'Azumatt-Lib-1.0.0'])]},
    {'full_name': 'Azumatt-Lib', 'loja': 'thunderstore', 'package_url': 'https://thunderstore.io/c/valheim/p/Azumatt/Lib/',
     'versions': [version('1.2.0')]},   # the Thunderstore catalog has no dependency list
    {'full_name': 'ValheimModding-Jotunn', 'loja': 'hexium', 'package_url': 'https://valheim.hexium.gg/mods/ValheimModding/Jotunn',
     'versions': [version('2.24.0', ['ValheimModding-YamlDotNet-16.3.1'])]},
]


def package(tmp_path, name, deps):
    path = tmp_path / f'{name}.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('manifest.json', json.dumps({'name': name, 'version_number': '1.2.0', 'dependencies': deps}))
    return path


@pytest.fixture
def store(tmp_path, monkeypatch):
    installed = {'ValheimModding-Jotunn': '2.24.0'}
    monkeypatch.setattr(executor, '_catalogo', lambda: CATALOG)
    monkeypatch.setattr(executor, '_instalados', lambda: dict(installed))
    downloads = []
    def download(name, number):
        downloads.append(f'{name}-{number}')
        return package(tmp_path, name, ['ValheimModding-YamlDotNet-16.3.1'] if name == 'Azumatt-Lib' else [])
    monkeypatch.setattr(executor, '_baixa', download)
    return installed, downloads


def test_finds_what_is_missing_without_installing(store):
    found = executor.v_mods_dependencias({'nome': 'RustyMods-Seasonality', 'versao': '3.8.3'})
    assert found['antigas'] == []
    assert found['faltando'] == [{'nome': 'ValheimModding-YamlDotNet', 'versao': '16.3.1',
                                  'url': 'https://valheim.hexium.gg/mods/ValheimModding/YamlDotNet',
                                  'loja': 'hexium', 'pedido_por': 'RustyMods-Seasonality'}]
    assert store[1] == []                                    # the catalog was enough: nothing downloaded


def test_dependencies_of_dependencies_come_first(store):
    found = executor.v_mods_dependencias({'nome': 'Azumatt-Needs', 'versao': '1.0.0'})
    # Jotunn is installed; Lib is not, and Lib needs YamlDotNet (read from its package).
    assert [d['nome'] for d in found['faltando']] == ['ValheimModding-YamlDotNet', 'Azumatt-Lib']
    assert found['faltando'][1]['versao'] == '1.2.0'         # 1.0.0 is gone: the oldest newer one
    assert store[1] == ['Azumatt-Lib-1.2.0']


def test_an_installed_dependency_too_old_is_reported(store):
    store[0]['ValheimModding-YamlDotNet'] = '16.0.0'
    found = executor.v_mods_dependencias({'nome': 'RustyMods-Seasonality', 'versao': '3.8.3'})
    assert found['faltando'] == []
    assert found['antigas'][0] | {} == {'nome': 'ValheimModding-YamlDotNet', 'precisa': '16.3.1', 'tem': '16.0.0',
                                        'url': 'https://valheim.hexium.gg/mods/ValheimModding/YamlDotNet',
                                        'pedido_por': 'RustyMods-Seasonality'}
    with pytest.raises(executor.Recusa, match='Atualize ValheimModding-YamlDotNet primeiro'):
        executor._com_dependencias('RustyMods-Seasonality', '3.8.3', [], print)


def test_installs_only_what_the_admin_confirmed(store):
    with pytest.raises(executor.Recusa, match='faltam dependências'):
        executor._com_dependencias('RustyMods-Seasonality', '3.8.3', None, print)
    with pytest.raises(executor.Recusa):
        executor._com_dependencias('RustyMods-Seasonality', '3.8.3', ['Something-Else-1.0.0'], print)
    done = executor._com_dependencias('RustyMods-Seasonality', '3.8.3', ['ValheimModding-YamlDotNet-16.3.1'], print)
    assert [name for name, _ in done] == ['ValheimModding-YamlDotNet']


def test_the_install_script_accepts_dependencies_in_the_same_batch():
    script = (ROOT / 'ferramentas/instalar-mods.py').read_text(encoding='utf-8')
    assert 'if dn in lote:' in script and "lock['packages'][dn]['version']\n" not in script.split('def versao_de')[0]


def test_the_mod_manager_shows_the_list_before_installing():
    page = (ROOT / 'servicos/painel/modelos/mods.html').read_text(encoding='utf-8')
    assert "verbo: 'mods.dependencias'" in page and "rotulo: 'Ver na loja'" in page
    assert "'mods.dependencias'" in (ROOT / 'servicos/painel/app.py').read_text(encoding='utf-8')
    assert 'opcoes.itens' in (ROOT / 'servicos/painel/estatico/avisos.js').read_text(encoding='utf-8')
