"""A wipe can name its new world without starting the game."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'servicos/painel'))
import executor  # noqa: E402


def test_wipe_uses_new_name_for_seed_and_server_config(tmp_path, monkeypatch):
    game = tmp_path / 'game'
    worlds = game / 'saves/worlds_local'
    worlds.mkdir(parents=True)
    wipes = game / 'wipes'
    wipes.mkdir()
    monkeypatch.setattr(executor, 'VALHEIM', game)
    monkeypatch.setattr(executor, 'MUNDOS', worlds)
    monkeypatch.setattr(executor, 'WIPES', wipes)
    monkeypatch.setattr(executor, 'TRAVA_MANUTENCAO', str(tmp_path / 'lock'))
    monkeypatch.setattr(executor, '_nome_do_mundo', lambda: 'Old')
    monkeypatch.setattr(executor, '_para_servidor', lambda anota: False)
    monkeypatch.setattr(executor, '_roda', lambda *args: None)
    monkeypatch.setattr(executor, '_modelo_fwl', lambda *args: object())
    monkeypatch.setattr(executor, '_arquiva_mundo', lambda *args: {})
    calls = []
    monkeypatch.setattr(executor, '_cria_mundo_com_seed',
                        lambda name, seed, model, anota: calls.append(('seed', name, seed)))
    monkeypatch.setattr(executor.operacoes, 'server_save',
                        lambda data: calls.append(('config', data)))
    monkeypatch.setattr(executor.sagas, 'refresh_current_world',
                        lambda path: calls.append(('map', path)))

    def run_task(title, steps):
        for step in steps:
            step(lambda line: None)
        return 'done'

    monkeypatch.setattr(executor, '_tarefa', run_task)
    result = executor.v_mundo_wipe({'confirmar': 'Old', 'mundo': True,
                                    'novo_nome': 'New World', 'seed': 'Seed123'})
    assert result == {'tarefa': 'done'}
    assert ('seed', 'New World', 'Seed123') in calls
    assert ('config', {'mundo': 'New World'}) in calls
    assert ('map', game) in calls
    record = next(wipes.iterdir()) / 'wipe.json'
    assert json.loads(record.read_text())['nome_novo'] == 'New World'


def test_wipe_rejects_an_existing_new_world(tmp_path, monkeypatch):
    worlds = tmp_path / 'worlds'
    (worlds / 'Taken').mkdir(parents=True)
    monkeypatch.setattr(executor, 'MUNDOS', worlds)
    monkeypatch.setattr(executor, '_nome_do_mundo', lambda: 'Old')
    with pytest.raises(executor.Recusa, match='já existe'):
        executor.v_mundo_wipe({'confirmar': 'Old', 'mundo': True, 'novo_nome': 'Taken'})
