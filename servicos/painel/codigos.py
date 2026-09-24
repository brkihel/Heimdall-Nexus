"""Error code catalog shown to admins (docs/CODIGOS-DE-ERRO.md mirrors it).

Format: HN-<AREA>-<NNN>. HN = Heimdall Nexus. The number never changes once
published; retired codes stay listed. Admin-facing text is pt-BR.
"""
from __future__ import annotations

import re

CODE = re.compile(r'^HN-[A-Z]{3,5}-\d{3}$')
PREFIXED = re.compile(r'^(HN-[A-Z]{3,5}-\d{3}): (.*)$', re.S)

CATALOGO: dict[str, dict[str, str]] = {
    # --- Updates: checking and starting (executor) ---
    'HN-UPD-001': {'titulo': 'Git não instalado',
                   'solucao': 'Na máquina do Nexus, rode: sudo apt install git'},
    'HN-UPD-002': {'titulo': 'O repositório demorou demais para responder',
                   'solucao': 'Confira a internet do servidor e tente de novo em alguns minutos.'},
    'HN-UPD-003': {'titulo': 'O Git não conseguiu baixar as versões',
                   'solucao': 'Confira se o servidor acessa github.com (curl -I https://github.com). O detalhe do Git aparece na mensagem.'},
    'HN-UPD-004': {'titulo': 'Endereço do repositório de atualização inválido',
                   'solucao': 'HEIMDALL_UPDATE_REPO em /etc/heimdall-nexus/heimdall.env precisa ser um endereço https://….git.'},
    'HN-UPD-005': {'titulo': 'A cópia local do repositório está danificada',
                   'solucao': 'Apague /var/lib/heimdall-nexus/source (sudo rm -rf) e procure atualizações de novo.'},
    'HN-UPD-006': {'titulo': 'O canal escolhido não existe no repositório',
                   'solucao': 'Escolha outro canal. Canais de desenvolvimento podem ser apagados depois de publicados no estável.'},
    'HN-UPD-007': {'titulo': 'Canal inválido',
                   'solucao': 'Use main ou um canal dev/… da lista.'},
    'HN-UPD-008': {'titulo': 'Versão inválida',
                   'solucao': 'Procure atualizações de novo e use o botão Atualizar.'},
    'HN-UPD-009': {'titulo': 'Já existe uma atualização em andamento',
                   'solucao': 'Aguarde a atual terminar; o progresso aparece nesta página.'},
    'HN-UPD-010': {'titulo': 'A lista de mudanças ficou desatualizada',
                   'solucao': 'O canal recebeu uma versão nova depois da sua procura. Procure de novo e confira a lista.'},
    'HN-UPD-011': {'titulo': 'Não foi possível iniciar a atualização',
                   'solucao': 'O systemd recusou a tarefa. Veja: sudo journalctl -u heimdall-executor -n 50'},
    'HN-UPD-012': {'titulo': 'Nenhuma procura recente',
                   'solucao': 'Clique em Procurar atualizações antes de atualizar.'},
    'HN-UPD-013': {'titulo': 'Esta versão já está instalada',
                   'solucao': 'Nada a fazer. Procure atualizações de novo mais tarde.'},
    # --- Updates: steps of deploy/update.sh ---
    'HN-UPD-100': {'titulo': 'Pré-requisitos da atualização não atendidos',
                   'solucao': 'A instalação não foi encontrada ou o script não rodou como root. Veja o registro técnico.'},
    'HN-UPD-101': {'titulo': 'Falha ao copiar o código novo',
                   'solucao': 'Confira o espaço em disco (df -h /opt). A versão anterior continua nos serviços até o reinício.'},
    'HN-UPD-102': {'titulo': 'Falha ao atualizar as bibliotecas do painel',
                   'solucao': 'O pip não conseguiu instalar as dependências. Confira a internet do servidor e tente de novo.'},
    'HN-UPD-103': {'titulo': 'Falha ao atualizar os serviços das Sagas',
                   'solucao': 'Veja: systemctl status heimdall-sagas-ingest.timer heimdall-sagas-story.timer'},
    'HN-UPD-104': {'titulo': 'Falha ao atualizar os ajudantes do site',
                   'solucao': 'Confira as permissões de /var/lib/heimdall-nexus/site. Suas páginas não foram alteradas.'},
    'HN-UPD-105': {'titulo': 'Falha ao publicar o site',
                   'solucao': 'O site anterior continua no ar. Veja o registro técnico e tente de novo.'},
    'HN-UPD-106': {'titulo': 'Falha ao atualizar a ponte Sagas',
                   'solucao': 'A ponte anterior continua instalada. Confira a pasta BepInEx/plugins/HeimdallSagas do servidor.'},
    'HN-UPD-107': {'titulo': 'Falha ao registrar a versão instalada',
                   'solucao': 'A atualização foi aplicada, mas a versão não foi gravada. Rode a atualização de novo.'},
    'HN-UPD-108': {'titulo': 'O painel não voltou depois de reiniciar',
                   'solucao': 'Veja: sudo journalctl -u heimdall-panel -n 80. Pelo terminal: cd ~/Heimdall-Nexus && sudo ./deploy/update.sh'},
    'HN-UPD-120': {'titulo': 'A atualização terminou sem trocar a versão',
                   'solucao': 'Veja o registro técnico. Se não houver erro nele, procure atualizações de novo.'},
    'HN-UPD-121': {'titulo': 'A atualização foi interrompida',
                   'solucao': 'O processo parou sem concluir (reinício da máquina ou falta de memória). Rode a atualização de novo.'},
    # --- Stories (Jarl > Sagas > Histórias) ---
    'HN-STO-001': {'titulo': 'Opções das histórias inválidas', 'solucao': 'Recarregue a página e salve as histórias de novo.'},
    'HN-STO-002': {'titulo': 'Histórias desligadas', 'solucao': 'Ligue "Extensão ativa" e "Abates e mortes" em Módulos e "Histórias ativas" no cartão de histórias.'},
    'HN-STO-003': {'titulo': 'Mundo ou Viking inválido', 'solucao': 'Recarregue a página e escolha de novo.'},
    'HN-STO-004': {'titulo': 'Chave de API não configurada', 'solucao': 'Cole a chave do provedor escolhido e clique em Guardar chave.'},
    'HN-STO-005': {'titulo': 'Chave de API inválida', 'solucao': 'Confira se a chave é do provedor escolhido (OpenRouter sk-or-…, OpenAI sk-…, Anthropic sk-ant-…).'},
    'HN-STO-006': {'titulo': 'Nenhum evento autorizado', 'solucao': 'O jogador precisa de ShareProfile e ShareStories como true no BepInEx e de ao menos um momento registrado.'},
    'HN-STO-007': {'titulo': 'Já existe uma história para esses momentos', 'solucao': 'Espere novos momentos serem registrados.'},
    'HN-STO-008': {'titulo': 'Limite diário de histórias atingido', 'solucao': 'O limite volta à meia-noite UTC. Aumente "Capítulos por dia" se quiser mais.'},
    'HN-STO-009': {'titulo': 'O provedor recusou o pedido', 'solucao': 'Se for limite de uso (HTTP 429) dos modelos grátis, o Nexus tenta de novo sozinho em 10 minutos. Veja a mensagem do provedor.'},
    'HN-STO-010': {'titulo': 'Sem conexão com o provedor', 'solucao': 'Confira a internet do servidor. O Nexus tenta de novo em 10 minutos.'},
    'HN-STO-011': {'titulo': 'O modelo respondeu fora do formato', 'solucao': 'Comum em modelos grátis. O Nexus tenta de novo em 10 minutos; se repetir, escolha um modelo específico.'},
    'HN-STO-012': {'titulo': 'A resposta não citou os registros', 'solucao': 'O Nexus tenta de novo em 10 minutos.'},
    'HN-STO-013': {'titulo': 'O compartilhamento mudou durante a geração', 'solucao': 'Um jogador retirou a permissão enquanto a história era escrita. Nada foi publicado.'},
    'HN-STO-014': {'titulo': 'O feito não está mais disponível', 'solucao': 'O registro foi apagado ou ocultado pelo filtro de abates.'},
    'HN-STO-015': {'titulo': 'Resposta grande demais do provedor', 'solucao': 'O Nexus tenta de novo em 10 minutos.'},
    'HN-STO-016': {'titulo': 'Pedido de história inválido', 'solucao': 'Peça de novo pelo botão Gerar história.'},
    'HN-STO-017': {'titulo': 'Sem créditos no provedor', 'solucao': 'Adicione créditos ou aumente o limite de gasto na conta do provedor.'},
    'HN-STO-018': {'titulo': 'Erro interno ao gerar a história', 'solucao': 'Veja: sudo journalctl -u heimdall-sagas-story -n 50'},
    # --- Mods (Jarl > Mods) ---
    'HN-MOD-001': {'titulo': 'A instalação do mod falhou',
                   'solucao': 'Os arquivos novos foram revertidos. Veja o registro técnico; se o download falhou, tente de novo em alguns minutos.'},
    'HN-MOD-002': {'titulo': 'A atualização do mod falhou',
                   'solucao': 'A versão anterior foi mantida. Veja o registro técnico e tente de novo.'},
    'HN-MOD-003': {'titulo': 'A remoção do mod falhou',
                   'solucao': 'Veja o registro técnico. A pasta do mod fica guardada nas cópias antes de sair.'},
    'HN-MOD-004': {'titulo': 'A procura por atualizações falhou',
                   'solucao': 'Confira a internet do servidor e tente de novo.'},
    # --- Server Config: access lists and world modifiers ---
    'HN-CFG-001': {'titulo': 'ID de jogador inválida',
                   'solucao': 'Use a Steam ID de 17 dígitos (começa com 7656119) ou Plataforma_ID, como Xbox_123…'},
    'HN-CFG-002': {'titulo': 'Nome de jogador inválido',
                   'solucao': 'Use até 40 caracteres, sem barra (/).'},
    'HN-CFG-003': {'titulo': 'A mesma ID está como admin e banida',
                   'solucao': 'Remova a ID de uma das duas listas.'},
    'HN-CFG-004': {'titulo': 'Whitelist ativa sem nenhum jogador',
                   'solucao': 'Adicione pelo menos um jogador (de preferência você como admin) antes de ativar.'},
    'HN-CFG-005': {'titulo': 'Pasta de saves do Valheim não encontrada',
                   'solucao': 'Confira VH_SAVEDIR em server.env (aba Arquivos) ou reinstale pelo instalador.'},
    'HN-CFG-006': {'titulo': 'Arquivo de lista é um link simbólico',
                   'solucao': 'Por segurança o painel não segue links. Substitua o link por um arquivo comum.'},
    'HN-CFG-007': {'titulo': 'Modificador de mundo inválido',
                   'solucao': 'Recarregue a página e escolha uma das opções mostradas.'},
    'HN-CFG-008': {'titulo': 'O lançador instalado não aceita modificadores',
                   'solucao': 'Atualize o Heimdall em Sobre e atualizações.'},
    'HN-CFG-009': {'titulo': 'Dados de acesso inválidos',
                   'solucao': 'Recarregue a página e tente de novo.'},
}


def com_codigo(codigo: str, mensagem: str) -> str:
    """Prefix a message so the code survives the executor/panel plumbing."""
    assert codigo in CATALOGO, codigo
    return f'{codigo}: {mensagem}'


def separa(texto: str) -> tuple[str, str]:
    match = PREFIXED.match(texto or '')
    return (match.group(1), match.group(2)) if match else ('', texto or '')
