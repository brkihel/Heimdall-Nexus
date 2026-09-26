"""Game status shown in Jarl follows the live systemd state and readiness."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'servicos/painel'))
pytest.importorskip('fastapi')
import app  # noqa: E402
import executor  # noqa: E402


@pytest.mark.parametrize('servico,codigo', [
    ({'ActiveState': 'active', 'Pronto': True}, 'no-ar'),
    ({'ActiveState': 'active', 'Pronto': False}, 'carregando'),
    ({'ActiveState': 'activating'}, 'iniciando'),
    ({'ActiveState': 'deactivating'}, 'parando'),
    ({'ActiveState': 'inactive'}, 'desligado'),
    ({'ActiveState': 'failed'}, 'falhou'),
    ({'erro': 'executor offline'}, 'desconhecido'),
])
def test_status_phases(servico, codigo):
    assert app.estado_do_jogo(servico)['codigo'] == codigo


def test_readiness_is_per_run_and_cached():
    executor._PRONTO_POR_EXECUCAO.clear()
    calls = []

    def fake_search(service, text, invocation):
        calls.append(invocation)
        return text == 'Game server connected' and invocation == 'a' * 32
    with patch.object(executor.hostos, 'service_logged_since_start', side_effect=fake_search):
        assert executor._jogo_pronto('a' * 32)
        assert executor._jogo_pronto('a' * 32)
        assert not executor._jogo_pronto('b' * 32)
        assert not executor._jogo_pronto('not-an-id')
    assert len(calls) == 2
