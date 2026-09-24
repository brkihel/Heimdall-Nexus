"""Admins, whitelist, bans and world modifiers, on temporary files only."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'servicos/painel'))
import operacoes  # noqa: E402

ADMIN = '76561198000000001'
PLAYER = '76561198000000002'


@pytest.fixture
def game(tmp_path, monkeypatch):
    saves = tmp_path / 'saves'
    saves.mkdir()
    env = tmp_path / 'server.env'
    env.write_text(f'VH_NAME="N"\nVH_WORLD="W"\nVH_PORT="2456"\nVH_SAVEDIR="{saves}"\n')
    launcher = tmp_path / 'launcher.sh'
    launcher.write_text('VH_MODIFIERS_MANAGED VH_PASSWORD\n')
    monkeypatch.setattr(operacoes, 'GAME', tmp_path)
    monkeypatch.setattr(operacoes, 'ENV', env)
    monkeypatch.setattr(operacoes, 'PROFILE', tmp_path / 'profile.json')
    monkeypatch.setattr(operacoes, '_launcher', lambda: launcher)
    monkeypatch.setattr(operacoes, 'online', lambda: False)
    monkeypatch.setattr(operacoes, '_user_exists', lambda name: False)
    return saves


def save(**changes):
    data = {'admins': [{'id': ADMIN, 'nome': 'Diego'}], 'whitelist_ativa': True,
            'whitelist': [{'id': PLAYER, 'nome': 'Astrid'}], 'banidos': []}
    return operacoes.access_save({**data, **changes})


def ids(path):
    return [line for line in path.read_text().splitlines() if line and not line.startswith('//')]


def test_whitelist_includes_admins_and_keeps_names(game):
    result = save()
    assert ids(game / 'permittedlist.txt') == [ADMIN, PLAYER]
    assert ids(game / 'adminlist.txt') == [ADMIN]
    assert result['whitelist'] == {'ativa': True, 'jogadores': [
        {'id': PLAYER, 'nome': 'Astrid', 'valida': True}]}
    assert result['admins'][0]['nome'] == 'Diego'


def test_disabled_whitelist_is_empty_for_valheim_but_remembered(game):
    result = save(whitelist_ativa=False)
    assert ids(game / 'permittedlist.txt') == []
    assert result['whitelist']['ativa'] is False
    assert [p['id'] for p in result['whitelist']['jogadores']] == [PLAYER]


def test_valheim_rewrite_and_in_game_ban_survive(game):
    save()
    # Valheim rewrites a list with its comments first, then IDs, after "ban".
    banned = game / 'bannedlist.txt'
    banned.write_text('// List banned players ID  ONE per line\n76561198000000009\n')
    result = operacoes.access_read()
    assert [b['id'] for b in result['banidos']] == ['76561198000000009']


def test_rejects_bad_ids_names_conflicts_and_empty_whitelist(game):
    for bad in ('123', '7656119800000000; rm -rf /', '', 'Steam_'):
        with pytest.raises(operacoes.Problem):
            save(whitelist=[{'id': bad, 'nome': 'x'}])
    with pytest.raises(operacoes.Problem):
        save(whitelist=[{'id': PLAYER, 'nome': 'a/b'}])
    with pytest.raises(operacoes.Problem):
        save(banidos=[{'id': ADMIN, 'nome': ''}])
    with pytest.raises(operacoes.Problem):
        save(admins=[], whitelist=[])
    assert operacoes.access_save({'admins': [], 'whitelist_ativa': False, 'whitelist': [],
                                  'banidos': []})['whitelist']['ativa'] is False


def test_crossplay_ids_are_accepted(game):
    result = save(whitelist=[{'id': 'Xbox_2535405290473213', 'nome': 'Bjorn'}])
    assert result['whitelist']['jogadores'][0]['id'] == 'Xbox_2535405290473213'


def test_modifiers_roundtrip_and_validation(game):
    choice = {'gerenciar': True, 'valores': {'combat': 'hard', 'deathpenalty': 'casual',
              'resources': 'default', 'raids': 'none', 'portals': 'veryhard'},
              'chaves': ['nomap', 'fire']}
    result = operacoes.server_save({'modificadores': choice})['configuracao']
    assert result['modificadores']['valores']['combat'] == 'hard'
    assert result['modificadores']['chaves'] == ['fire', 'nomap']
    command = result['comando']
    assert '-resetmodifiers' in command and command.count('-modifier') == 4
    assert 'resources' not in command
    env = operacoes.ENV.read_text()
    assert 'VH_MODIFIERS="combat=hard,deathpenalty=casual,raids=none,portals=veryhard"' in env
    for bad in ({**choice, 'valores': {**choice['valores'], 'combat': 'godmode'}},
                {**choice, 'chaves': ['nomap; reboot']},
                {**choice, 'gerenciar': 'yes'}):
        with pytest.raises(operacoes.Problem):
            operacoes.server_save({'modificadores': bad})
    off = operacoes.server_save({'modificadores': {**choice, 'gerenciar': False}})['configuracao']
    assert '-resetmodifiers' not in off['comando']


def test_launcher_passes_only_known_modifiers(tmp_path):
    import os
    import subprocess
    (tmp_path / 'linux64').mkdir()
    fake = tmp_path / 'valheim_server.x86_64'
    fake.write_text('#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done\n')
    fake.chmod(0o755)
    base = {'PATH': '/usr/bin:/bin', 'VH_GAMEDIR': str(tmp_path), 'VH_NAME': 'N', 'VH_PORT': '2456',
            'VH_WORLD': 'W', 'VH_SAVEDIR': '/s'}
    script = str(Path(__file__).resolve().parents[1] / 'deploy/valheim-launch.sh')

    def run(**env):
        return subprocess.run(['bash', script], env={**base, **env}, capture_output=True,
                              text=True, check=True).stdout.split('\n')
    args = run(VH_MODIFIERS_MANAGED='1', VH_MODIFIERS='combat=hard,evil=$(id),raids=none',
               VH_SETKEYS='nomap,rm -rf /')
    assert args[args.index('-resetmodifiers'):] == ['-resetmodifiers', '-modifier', 'combat', 'hard',
                                                    '-modifier', 'raids', 'none', '-setkey', 'nomap', '']
    assert '-resetmodifiers' not in run(VH_MODIFIERS='combat=hard')


def test_panel_installer_and_launcher_offer_the_same_modifiers():
    import re
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'deploy'))
    import installer
    assert installer.MODIFIERS == operacoes.MODIFIERS
    assert installer.WORLD_KEYS == operacoes.WORLD_KEYS
    launcher = (root / 'deploy/valheim-launch.sh').read_text()
    allowed = set(re.findall(r'(\w+)=(\w+)[|)]', launcher))
    expected = {(name, value) for name, values in operacoes.MODIFIERS.items()
                for value in values if value != 'default'}
    assert allowed == expected
    keys = re.search(r'\n\s*(playerevents[^)]*)\)', launcher).group(1).split('|')
    assert tuple(keys) == operacoes.WORLD_KEYS
