#!/usr/bin/env python3
"""Regenerate docs/CODIGOS-DE-ERRO.md from servicos/painel/codigos.py."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'servicos/painel'))
import codigos  # noqa: E402

AREAS = {'UPD': 'Atualizações pelo Jarl e `deploy/update.sh`',
         'CFG': 'Server Config: admins, whitelist, banidos e modificadores de mundo'}


def render() -> str:
    lines = ['# Códigos de erro do Heimdall Nexus', '',
             'Todo erro que o Jarl mostra ao administrador tem um código `HN-ÁREA-NNN`.',
             'HN é Heimdall Nexus; a área diz de onde vem a falha; o número nunca muda depois de',
             'publicado. Ao relatar um problema, mande o código: ele diz de cara onde procurar.', '',
             'A fonte da verdade é `servicos/painel/codigos.py`; esta página é gerada a partir',
             'dele (`python3 ferramentas/gerar-codigos.py`) e um teste confere que as duas batem.', '',
             '| Área | Significado |', '|---|---|']
    lines += [f'| {area} | {meaning} |' for area, meaning in AREAS.items()]
    lines += ['', '| Código | O que houve | Como resolver |', '|---|---|---|']
    for code, info in codigos.CATALOGO.items():
        lines.append(f"| `{code}` | {info['titulo']} | {info['solucao'].replace('|', chr(92) + '|')} |")
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    (ROOT / 'docs/CODIGOS-DE-ERRO.md').write_text(render())
