"""Schedule and settings checks use temporary files; no systemd command runs."""
import datetime as dt
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'servicos/painel'))
import operacoes  # noqa: E402


def test_cron_ranges_and_weekday():
    monday = dt.datetime(2026, 9, 28, 4, 15)
    assert operacoes.cron_match('*/15 4 * * 1', monday)
    assert not operacoes.cron_match('*/15 4 * * 2', monday)
    assert operacoes.cron_match('15 4 28 * 2', monday)  # day or weekday
    with pytest.raises(operacoes.Problem):
        operacoes.cron_match('61 4 * * *', monday)


def test_schedule_roundtrip_and_allowlist(tmp_path, monkeypatch):
    monkeypatch.setattr(operacoes, 'SCHEDULES', tmp_path / 'schedules.json')
    item = operacoes.schedules_save({'nome': 'Backup diário', 'cron': '0 4 * * *',
                                     'ativo': True, 'apenas_online': True,
                                     'tarefas': [{'acao': 'backup', 'atraso': 0}]})
    assert operacoes.schedules_list()[0]['id'] == item['id']
    with pytest.raises(operacoes.Problem):
        operacoes.schedules_save({'nome': 'perigoso', 'cron': '* * * * *',
                                  'tarefas': [{'acao': 'shell', 'comando': 'echo no'}]})
    operacoes.schedules_delete(item['id'])
    assert operacoes.schedules_list() == []


def test_server_config_keeps_password_hidden(tmp_path, monkeypatch):
    env = tmp_path / 'server.env'
    env.write_text('VH_NAME="Old Name"\nVH_WORLD="World"\nVH_PORT="2456"\nVH_PASSWORD="secret"\n')
    launcher = tmp_path / 'launcher.sh'
    launcher.write_text('args+=(-password "$VH_PASSWORD")\n')
    monkeypatch.setattr(operacoes, 'GAME', tmp_path)
    monkeypatch.setattr(operacoes, 'ENV', env)
    monkeypatch.setattr(operacoes, 'PROFILE', tmp_path / 'profile.json')
    monkeypatch.setattr(operacoes, '_launcher', lambda: launcher)
    monkeypatch.setattr(operacoes, 'online', lambda: False)
    before = operacoes.server_read()
    assert 'secret' not in str(before)
    operacoes.server_save({'nome': 'New Name', 'descricao': 'Test server'})
    assert 'VH_PASSWORD="secret"' in env.read_text()
    assert 'VH_NAME="New Name"' in env.read_text()
    assert operacoes.server_read()['descricao'] == 'Test server'


def test_archive_name_blocks_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(operacoes, 'BACKUPS', tmp_path)
    with pytest.raises(operacoes.Problem):
        operacoes._archive('../../server.env')


def test_backup_create_and_restore_in_isolated_directory(tmp_path, monkeypatch):
    import pwd
    game = tmp_path / 'game'
    saves = game / 'saves'
    saves.mkdir(parents=True)
    world = saves / 'world.db2'
    world.write_bytes(b'old world')
    monkeypatch.setattr(operacoes, 'GAME', game)
    monkeypatch.setattr(operacoes, 'BACKUPS', game / 'backups')
    monkeypatch.setattr(operacoes, 'MAINTENANCE_LOCK', tmp_path / 'maintenance.lock')
    monkeypatch.setattr(operacoes, 'online', lambda: False)
    monkeypatch.setattr(pwd, 'getpwnam', lambda _: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()))
    archive = operacoes.backup_create()
    world.write_bytes(b'changed world')
    safety = operacoes.backup_restore(archive)
    assert world.read_bytes() == b'old world'
    assert (game / 'backups' / safety).is_file()


def test_password_cannot_be_inside_server_name(tmp_path, monkeypatch):
    env = tmp_path / 'server.env'
    env.write_text('VH_NAME="Norte"\nVH_WORLD="World"\nVH_PORT="2456"\nVH_PASSWORD="secret"\n')
    launcher = tmp_path / 'launcher.sh'
    launcher.write_text('args+=(-password "$VH_PASSWORD")\n')
    monkeypatch.setattr(operacoes, 'GAME', tmp_path)
    monkeypatch.setattr(operacoes, 'ENV', env)
    monkeypatch.setattr(operacoes, 'PROFILE', tmp_path / 'profile.json')
    monkeypatch.setattr(operacoes, '_launcher', lambda: launcher)
    monkeypatch.setattr(operacoes, 'online', lambda: False)
    with pytest.raises(operacoes.Problem):
        operacoes.server_save({'nome': 'Secret Club'})
    with pytest.raises(operacoes.Problem):
        operacoes.server_save({'senha': 'norte'})
    operacoes.server_save({'nome': 'Clube do Norte', 'senha': 'machado'})
    assert 'VH_PASSWORD="machado"' in env.read_text()


def test_password_removal_needs_blank_password_mod(tmp_path, monkeypatch):
    game = tmp_path / 'game'
    plugins = game / 'current/BepInEx/plugins/1010101110-serverblankpassword'
    env = game / 'server.env'
    game.mkdir()
    env.write_text('VH_NAME="Norte"\nVH_WORLD="World"\nVH_PASSWORD="secret"\nVH_BEPINEX="1"\n')
    launcher = tmp_path / 'launcher.sh'
    launcher.write_text('args+=(-password "$VH_PASSWORD")\n')
    monkeypatch.setattr(operacoes, 'GAME', game)
    monkeypatch.setattr(operacoes, 'ENV', env)
    monkeypatch.setattr(operacoes, 'PROFILE', tmp_path / 'profile.json')
    monkeypatch.setattr(operacoes, '_launcher', lambda: launcher)
    monkeypatch.setattr(operacoes, 'online', lambda: False)
    with pytest.raises(operacoes.Problem):
        operacoes.server_save({'remover_senha': True})
    assert 'VH_PASSWORD="secret"' in env.read_text()
    plugins.mkdir(parents=True)
    (plugins / 'serverblankpassword.dll').write_bytes(b'dll')
    assert operacoes.server_read()['mod_sem_senha'] == 'serverblankpassword'
    operacoes.server_save({'remover_senha': True})
    assert 'VH_PASSWORD=""' in env.read_text()
    assert operacoes.server_read()['senha_definida'] is False
