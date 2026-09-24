# Códigos de erro do Heimdall Nexus

Todo erro que o Jarl mostra ao administrador tem um código `HN-ÁREA-NNN`.
HN é Heimdall Nexus; a área diz de onde vem a falha; o número nunca muda depois de
publicado. Ao relatar um problema, mande o código: ele diz de cara onde procurar.

A fonte da verdade é `servicos/painel/codigos.py`; esta página é gerada a partir
dele (`python3 ferramentas/gerar-codigos.py`) e um teste confere que as duas batem.

| Área | Significado |
|---|---|
| UPD | Atualizações pelo Jarl e `deploy/update.sh` |
| CFG | Server Config: admins, whitelist, banidos e modificadores de mundo |
| MOD | Instalar, atualizar e remover mods pelo Jarl |

| Código | O que houve | Como resolver |
|---|---|---|
| `HN-UPD-001` | Git não instalado | Na máquina do Nexus, rode: sudo apt install git |
| `HN-UPD-002` | O repositório demorou demais para responder | Confira a internet do servidor e tente de novo em alguns minutos. |
| `HN-UPD-003` | O Git não conseguiu baixar as versões | Confira se o servidor acessa github.com (curl -I https://github.com). O detalhe do Git aparece na mensagem. |
| `HN-UPD-004` | Endereço do repositório de atualização inválido | HEIMDALL_UPDATE_REPO em /etc/heimdall-nexus/heimdall.env precisa ser um endereço https://….git. |
| `HN-UPD-005` | A cópia local do repositório está danificada | Apague /var/lib/heimdall-nexus/source (sudo rm -rf) e procure atualizações de novo. |
| `HN-UPD-006` | O canal escolhido não existe no repositório | Escolha outro canal. Canais de desenvolvimento podem ser apagados depois de publicados no estável. |
| `HN-UPD-007` | Canal inválido | Use main ou um canal dev/… da lista. |
| `HN-UPD-008` | Versão inválida | Procure atualizações de novo e use o botão Atualizar. |
| `HN-UPD-009` | Já existe uma atualização em andamento | Aguarde a atual terminar; o progresso aparece nesta página. |
| `HN-UPD-010` | A lista de mudanças ficou desatualizada | O canal recebeu uma versão nova depois da sua procura. Procure de novo e confira a lista. |
| `HN-UPD-011` | Não foi possível iniciar a atualização | O systemd recusou a tarefa. Veja: sudo journalctl -u heimdall-executor -n 50 |
| `HN-UPD-012` | Nenhuma procura recente | Clique em Procurar atualizações antes de atualizar. |
| `HN-UPD-013` | Esta versão já está instalada | Nada a fazer. Procure atualizações de novo mais tarde. |
| `HN-UPD-100` | Pré-requisitos da atualização não atendidos | A instalação não foi encontrada ou o script não rodou como root. Veja o registro técnico. |
| `HN-UPD-101` | Falha ao copiar o código novo | Confira o espaço em disco (df -h /opt). A versão anterior continua nos serviços até o reinício. |
| `HN-UPD-102` | Falha ao atualizar as bibliotecas do painel | O pip não conseguiu instalar as dependências. Confira a internet do servidor e tente de novo. |
| `HN-UPD-103` | Falha ao atualizar os serviços das Sagas | Veja: systemctl status heimdall-sagas-ingest.timer heimdall-sagas-story.timer |
| `HN-UPD-104` | Falha ao atualizar os ajudantes do site | Confira as permissões de /var/lib/heimdall-nexus/site. Suas páginas não foram alteradas. |
| `HN-UPD-105` | Falha ao publicar o site | O site anterior continua no ar. Veja o registro técnico e tente de novo. |
| `HN-UPD-106` | Falha ao atualizar a ponte Sagas | A ponte anterior continua instalada. Confira a pasta BepInEx/plugins/HeimdallSagas do servidor. |
| `HN-UPD-107` | Falha ao registrar a versão instalada | A atualização foi aplicada, mas a versão não foi gravada. Rode a atualização de novo. |
| `HN-UPD-108` | O painel não voltou depois de reiniciar | Veja: sudo journalctl -u heimdall-panel -n 80. Pelo terminal: cd ~/Heimdall-Nexus && sudo ./deploy/update.sh |
| `HN-UPD-120` | A atualização terminou sem trocar a versão | Veja o registro técnico. Se não houver erro nele, procure atualizações de novo. |
| `HN-UPD-121` | A atualização foi interrompida | O processo parou sem concluir (reinício da máquina ou falta de memória). Rode a atualização de novo. |
| `HN-MOD-001` | A instalação do mod falhou | Os arquivos novos foram revertidos. Veja o registro técnico; se o download falhou, tente de novo em alguns minutos. |
| `HN-MOD-002` | A atualização do mod falhou | A versão anterior foi mantida. Veja o registro técnico e tente de novo. |
| `HN-MOD-003` | A remoção do mod falhou | Veja o registro técnico. A pasta do mod fica guardada nas cópias antes de sair. |
| `HN-MOD-004` | A procura por atualizações falhou | Confira a internet do servidor e tente de novo. |
| `HN-CFG-001` | ID de jogador inválida | Use a Steam ID de 17 dígitos (começa com 7656119) ou Plataforma_ID, como Xbox_123… |
| `HN-CFG-002` | Nome de jogador inválido | Use até 40 caracteres, sem barra (/). |
| `HN-CFG-003` | A mesma ID está como admin e banida | Remova a ID de uma das duas listas. |
| `HN-CFG-004` | Whitelist ativa sem nenhum jogador | Adicione pelo menos um jogador (de preferência você como admin) antes de ativar. |
| `HN-CFG-005` | Pasta de saves do Valheim não encontrada | Confira VH_SAVEDIR em server.env (aba Arquivos) ou reinstale pelo instalador. |
| `HN-CFG-006` | Arquivo de lista é um link simbólico | Por segurança o painel não segue links. Substitua o link por um arquivo comum. |
| `HN-CFG-007` | Modificador de mundo inválido | Recarregue a página e escolha uma das opções mostradas. |
| `HN-CFG-008` | O lançador instalado não aceita modificadores | Atualize o Heimdall em Sobre e atualizações. |
| `HN-CFG-009` | Dados de acesso inválidos | Recarregue a página e tente de novo. |
