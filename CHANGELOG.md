# Heimdall Nexus — versões

## 0.2.1

- O mapa público pode usar um gerador de mapas próprio da instalação, com até
  três estilos (Vanilla, Topográfico e Birds Eye) e um seletor na página. Basta
  apontar `HEIMDALL_EXTERNAL_ATLAS_DIR` para a exportação privada. As tiles
  continuam passando pelo modo de mapa do admin e pelo consentimento atual dos
  jogadores, e uma exportação de outro mundo (por exemplo, de antes de um wipe)
  é ignorada.
- Ponte Sagas 0.1.7: não gera o próprio mapa quando o gerador externo está em
  uso (`HEIMDALL_SAGAS_EXTERNAL_ATLAS=1`).
- O instalador da ponte aceita uma pasta do jogo sem link simbólico.
- O menu do site mostra o nome do servidor em todas as páginas.

Atualize pelo Jarl em **Sobre e atualizações**, no canal **Estável (main)**. Se
a ponte Sagas mudar, reinicie o Valheim quando puder.

## 0.2.0

Esta versão reúne o assistente de instalação, o Jarl e o site editável com a
extensão opcional Sagas. O Jarl agora mostra a versão do Nexus e a revisão Git
separadamente. As DLLs da extensão mantêm suas versões próprias.

### Novidades

- Páginas públicas próprias para mapa Birds Eye, histórias, armaria e rankings,
  com navegação configurável no editor e destaques de momentos na página inicial.
- Histórias sob pedido ou automáticas após grandes feitos, com provedores
  OpenRouter, OpenAI, Anthropic e Gemini; consentimento do jogador e limites
  de uso continuam obrigatórios.
- Mapa Birds Eye com compartilhamento opcional, terras conhecidas e controle
  de acesso às tiles; arte de chefes nos registros de lutas e nos capítulos.
- Modificadores de mundo no instalador e no Jarl; administração de admins,
  whitelist e banidos pela Server Config.
- Atualização pelo Jarl, com progresso, avisos e códigos de erro; status ao vivo
  do servidor e avisos mais curtos durante a instalação de mods.

### Instalações existentes

No Jarl, abra **Sobre e atualizações**, escolha **Estável (main)**, procure
atualizações e confira a versão antes de instalar. Se a instalação ainda não
tem essa aba, atualize uma vez pelo terminal:

```bash
cd ~/Heimdall-Nexus
git fetch origin
git switch main
git pull --ff-only origin main
sudo ./deploy/update.sh
```

O atualizador preserva mundos, mods, configurações e páginas editadas. Se ele
trocar a ponte Sagas, reinicie o Valheim quando puder para carregar a nova DLL.
O cliente Sagas é instalado à parte e continua exigindo consentimento explícito.

### Escopo

Sagas permanece uma extensão opcional em prévia. O port de todas as funções
do ValheimSagas segue na [devroad](docs/SAGAS-EXTENSION.md); o número 0.2.0 é
da plataforma Heimdall Nexus, não da DLL cliente ou da ponte.
