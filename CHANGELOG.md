# Heimdall Nexus — versões

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
