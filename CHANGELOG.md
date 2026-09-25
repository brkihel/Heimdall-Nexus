# Heimdall Nexus — versões

## 0.2.5

- O editor do menu mostra a hierarquia e os controles em cartões com espaço
  para edição, criação de links e mudança de nível. A página de adição informa
  quando todas as páginas já estão no menu.
- O editor em tela cheia tem um botão para voltar à página em edição na mesma aba.

## 0.2.4

- O ícone da estação no Console acompanha a estação informada pelo Seasonality,
  inclusive após redefinir o ciclo.

## 0.2.3

- O editor do menu organiza páginas em um nível de links filhos. No site,
  o submenu abre ao passar o mouse, com o teclado ou pela seta no celular;
  o link pai continua clicável.
- O wipe permite escolher o nome do novo mundo junto da seed e dos
  modificadores, sem iniciar o jogo automaticamente.
- O mapa público mostra apenas o mundo configurado no servidor, sem seletor.
  Após trocar ou apagar o mundo, dados e tiles antigos ficam indisponíveis
  enquanto o novo mundo não é gerado e registrado.

## 0.2.2

- O wipe de mundo permite definir os modificadores que serão aplicados no
  próximo início do servidor, usando as mesmas regras da Server Config.
- Instalação, atualização e remoção de mods, wipes, troca de mundo e backups
  deixam o jogo desligado. O início do jogo fica a cargo do administrador.
- O mapa público escolhe por padrão o mundo com atividade mais recente e
  descobre exportações de geradores externos em `/srv/*-web/mapa`, mantendo a
  checagem do UID e as regras de compartilhamento das tiles.
- O editor em tela cheia permite adicionar e remover páginas do menu público.
- O Jarl reúne o Editor de layout e as Configurações Globais em Aparência,
  explica quais páginas têm conteúdo próprio e corrige o favicon de páginas
  antigas durante a publicação.

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
