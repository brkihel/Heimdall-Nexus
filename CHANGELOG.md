# Heimdall Nexus — versões

## 1.1.0

Linux e Windows com suporte completo. O mesmo Heimdall Nexus, com o mesmo
assistente, painel, site e Sagas, agora instala e roda nos dois sistemas.

- **Windows nativo.** O Heimdall Nexus agora instala e roda no Windows 10
  (1809+), 11 e Server 2019/2022, sem WSL nem Docker: `install.ps1` instala um
  Python privado e abre o mesmo assistente visual. O servidor, o painel e o
  site viram serviços do Windows (WinSW), cada um com uma conta virtual própria
  e só as pastas de que precisa; o Caddy serve o site com HTTPS automático.
  Atualização pelo Jarl, `update.py`, `uninstall.ps1` (guarda os mundos, a
  menos que peça) e `install-sagas.py` completam o ciclo.
- **Uma base de código para os dois sistemas.** Tudo o que depende do sistema
  passou para `servicos/painel/hostos`. No Linux o comportamento é o mesmo de
  antes; no Windows, o executor fala com o painel em 127.0.0.1 com
  autenticação mútua por segredo compartilhado, que nunca atravessa a conexão.
- **Correções que valem para os dois sistemas:** as conexões do banco das
  Sagas passam a ser fechadas no fim de cada bloco; um modpack `.zip` local é
  reconhecido por qualquer caminho absoluto; a caixa de entrada das Sagas
  recusa links também onde não existe `O_NOFOLLOW`; regravar um arquivo pelo
  painel mantém as permissões do original.
- **Aba Mundo:** "Usar um mundo gerado no jogo" aceita mundos comuns; a exigência
  do Riverheim só vale em servidores que usam esse mod.
- **Assistente de instalação:** o botão "Instalar o modpack no servidor" não
  fica mais espremido, e no Windows o HTTPS começa desligado, porque quase
  toda instalação doméstica usa um IP.
- **Documentação:** guias de instalação separados para Linux e Windows, com
  referência rápida para veteranos, e os equivalentes do Windows em Operação,
  Configuração e Sagas.

## 1.0.0

Primeira versão estável. Reúne tudo o que veio nas 0.2.x:

- **Servidor:** instalação guiada, Server Config com modificadores e listas de
  acesso, wipe e troca de mundo, Mod Manager, Tarefas, Backups, Logs,
  Auditoria e atualização pelo próprio Jarl, em canais estável ou de
  desenvolvimento.
- **Site:** Layout Editor no estilo construtor de páginas, menu com
  submenus editado arrastando, Páginas, Configurações Globais, Modpack
  sincronizado com o Hexium e atalhos do Jarl nas páginas para quem está
  logado.
- **Sagas (opcional):** mapa Birds Eye, momentos, Armaria com retrato e
  equipamento, rankings recentes e histórias com IA, tudo sob o consentimento
  de cada jogador.
- As confirmações do painel usam uma caixa própria, que o navegador não
  consegue bloquear.
- O Mod Manager avisa corretamente que instalar, atualizar ou remover um mod
  deixa o servidor desligado.
- Documentação e wiki revistas para a 1.0, com capturas novas.

## 0.2.9

- As confirmações do Jarl (ligar, reiniciar, apagar, wipe, restaurar…) usam
  uma caixa do próprio painel em vez da janela do navegador. Antes, quem
  marcava "impedir esta página de criar caixas de diálogo" via os botões
  pararem sem aviso, porque o navegador passava a responder "não". Ações
  perigosas aparecem em vermelho e começam com o foco em Cancelar.

## 0.2.8

- **Aparência › Modpack**: compara a lista de mods do site com o modpack
  publicado no Hexium (versão, mods novos, que saíram e com versão nova) e
  publica a lista atualizada com um clique. Mods novos sem descrição em
  português aparecem para você escrever antes de publicar; as descrições
  ficam guardadas para as próximas atualizações. Nada muda no site até
  aplicar, e a versão aplicada é sempre a que foi verificada.

## 0.2.7

- **Armaria** virou a página de perfil de cada Viking: equipamento com os
  ícones do jogo em volta de um retrato do personagem, barra rápida 1–8 com o
  item em uso, vida, vigor, eitr e armadura, detalhes de cada item ao passar o
  mouse (atributos, efeitos, engastes do Jewelcrafting) e a aba Saga com os
  feitos do Viking. A página é toda o ambiente da Armaria, sem o bloco de
  título; com imagens `armaria-<bioma>.webp`, o fundo acompanha o bioma do
  último feito compartilhado.
- Heimdall Sagas Client e Bridge 0.2.1 enviam os ícones e o retrato. O retrato
  é tirado pelo jogo quando o visual muda; a seção `[Portrait]` do cliente
  liga, desliga e ajusta luz e câmera, e F9 refaz na hora. Tudo segue o
  `ShareProfile` do jogador e a opção de equipamento do admin.
- A captura de ícones e retrato é adaptada do Valheim Sagas (MIT).

## 0.2.6

- No site, quem está logado no Jarl vê os atalhos **Jarl** e **Layout Editor**
  no canto direito da barra de navegação, em todas as páginas. O painel
  flutuante no canto inferior direito e o modo edição dentro da própria página
  saíram: editar é sempre no Layout Editor, com a barra lateral.
- O Layout Editor funciona como um construtor de páginas: a barra começa na
  lista de seções; clicar em algo da página mostra só as ferramentas daquilo,
  em Conteúdo, Estilo e Bloco, com as escolhas abertas no próprio painel e
  **← Voltar** para a lista. Adicionar, Menu e Página ficam no rodapé.
- A navegação por pontos ao lado da página deixou de ser editável: ela segue
  as seções sozinha.
- O menu do site é editado ao clicar nele na página ou em Menu: arraste pela
  alça para ordenar e para os lados para entrar ou sair de um submenu. A barra
  da página mostra o resultado antes de salvar.
- Armaria, Rankings e Histórias não mostram mais o seletor de mundo: o site
  mostra sempre o mundo atual do servidor.
- Jarl: Mods virou **Mod Manager** e Crônica virou **Logs**. Criar e remover
  páginas do site ficou num item próprio, **Páginas**, em Aparência.
- Server Config: **Opções de inicialização** mostra os argumentos numa caixa
  somente leitura, uma opção por linha.

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
