# Padrões GenesisMods

Vale para tudo o que a GenesisMods produz: Heimdall Nexus (site, Jarl,
instalador, extensões), o servidor principal da GenesisMods e os mods da linha Genesis. Quando um
padrão daqui conflitar com o código existente, o padrão vence e o código entra
na fila de ajuste.

## 1. Pilares, em ordem de prioridade

1. **Segurança.** Dados dos jogadores, chaves, servidor e site. Nenhuma
   funcionalidade justifica abrir uma brecha. Na dúvida, fica desligado.
2. **Simplicidade e didática.** Um iniciante precisa conseguir usar sem ajuda;
   um veterano, sem perder tempo. Todo passo é explicado.
3. **Visual limpo, agradável e temático.** Valheim antes de tudo: noite,
   ouro, pedra, fogo. Nada de enfeite que atrapalhe a leitura.

## 2. Segurança (checklist de toda entrega)

- **Opt-in por padrão.** Recurso que envia ou mostra dado de jogador começa
  desligado, para o admin e para o jogador. Cada tipo de dado tem sua própria
  permissão (perfil, mapa, posição, histórias).
- **Revogar apaga.** Retirar uma permissão apaga o que ela autorizou, não só
  esconde. A leitura pública confere o consentimento atual a cada pedido.
- **Segredos.** Chaves ficam em arquivo `0600`, fora do banco, do navegador e
  dos logs. A auditoria registra "chave definida", nunca o valor.
- **Nenhuma porta nova.** O jogo não abre servidor web. Tudo público passa
  pelo Nginx e pelo painel já existentes, com rotas exatas.
- **Nada de terceiros no navegador do visitante.** Fontes, scripts e imagens
  são servidos pelo próprio Nexus (Cinzel e Spectral ficam em
  `assets/fontes/`, licença OFL). Nenhuma página pede recursos ao Google ou a
  CDNs, e o instalador mantém CSP `'self'`.
- **Menor privilégio.** Cada serviço roda com o usuário e as pastas mínimas
  (systemd com `ProtectSystem`, `NoNewPrivileges`). Arquivos do servidor do
  jogo pertencem ao usuário `valheim`.
- **Validar na borda.** Todo dado vindo do jogo, do navegador ou de um
  provedor externo é validado (tipo, tamanho, formato) antes de ser usado.
  O servidor confere o que o cliente afirma sempre que puder (posição,
  identidade, dono do objeto).
- **Limites.** Filas, lotes, tamanhos de resposta, tentativas por dia e
  armazenamento têm teto.
- **Escrita atômica.** Arquivo temporário + `fsync` + `replace`. Nada de
  arquivo pela metade depois de uma queda.
- **Nunca testar em produção.** Primeiro testes automatizados, depois a VM de
  teste; produção só depois de validado.

## 3. Didática (como falar com o usuário)

- **Todo recurso opcional tem um cartão "Para funcionar".** Lista o que é
  necessário (ponte instalada, mod no modpack, permissão do jogador, chave de
  API) com o estado de cada item conferido pelo sistema: ✓ pronto, ◌ falta,
  e o próximo passo concreto.
- **Estado sempre visível.** Nunca "verificando…" parado nem painel vazio.
  Sem dados, diga por quê e o que fazer. Erro diz o que houve e como resolver.
- **Poucos cliques até o conteúdo.** Mostre o essencial primeiro; detalhes em
  divulgação progressiva.
- **Passo a passo completo.** Instrução para o usuário traz todos os comandos,
  na ordem, sem pressupor conhecimento. Uma pessoa sozinha, com um cliente,
  consegue testar tudo.
- **Custos e riscos às claras.** Se algo custa dinheiro (API paga), revela o
  mundo (mapa inteiro) ou envia dados para fora (provedor de IA), o texto diz
  isso ao lado da opção.
- **Idioma.** Texto ao jogador em pt-BR, com sabor nórdico quando couber, mas
  claro. Código, logs e comentários em inglês.

### Códigos de erro e avisos

- **Todo erro mostrado ao administrador tem código** `HN-ÁREA-NNN`
  (HN = Heimdall Nexus). O catálogo único fica em
  `servicos/painel/codigos.py`, com título e "como resolver" em pt-BR;
  `docs/CODIGOS-DE-ERRO.md` é gerado dele e um teste confere os dois. Um
  número publicado nunca muda de significado. Área nova ganha sigla própria
  (UPD = atualizações).
- **Avisos flutuantes** (`estatico/avisos.js`, função `avisar`): sucesso e
  informação somem sozinhos em poucos segundos, com uma barra de tempo; erro
  fica até o usuário fechar e mostra o código, o que houve, como resolver e um
  botão para copiar o código.
- **Tarefas demoradas mostram progresso real**: etapa atual, passo N de T,
  tempo decorrido e registro técnico recolhido. Scripts anunciam etapas com
  `::heimdall step N/T CÓDIGO`, falhas com `::heimdall fail CÓDIGO` e o fim com
  `::heimdall done`.

## 4. Identidade visual

A identidade nasce do servidor principal da GenesisMods: não é copiar o site, é usar a mesma
linguagem. A referência de experiência é o ValheimSagas (seção 5), traduzido
para esta linguagem. Nenhum código, ilustração ou captura de terceiros é
copiado; artes são originais.

### Cores

| Token | Valor | Uso |
|---|---|---|
| `--breu` | `#05090d` | fundo da página |
| `--noite` | `#080e14` | barras, cabeçalho |
| `--carvao` | `#0d151d` | campos, superfícies baixas |
| `--ardosia` | `#152029` | superfícies elevadas |
| `--borda` / `--borda-viva` | `#22313d` / `#33475a` | contornos em repouso / foco e hover |
| `--ouro` / `--ouro-claro` / `--ouro-fundo` | `#c8a45c` / `#eeddb0` / `#7d6331` | destaque, títulos em ênfase, preenchimentos discretos |
| `--brasa` / `--brasa-clara` | `#ff8b3d` / `#ffc477` | fogo, perigo, mortes |
| `--osso` | `#e6e0d2` | títulos e texto forte |
| `--texto` / `--fraco` | `#b4bec7` / `#78848f` | corpo / legendas |
| `--bom` / `--ruim` / `--atencao` | `#7fd9a2` / `#ef8e7c` / `#d8b13f` | estados |

Cores de dados do jogo (biomas, raridade) ficam numa paleta própria e só
aparecem sobre dados: mapa, itens, gráficos.

### Tipografia

- **Cinzel** para títulos, rótulos e botões. Rótulo: caixa-alta,
  espaçamento `.2em`, `.64rem`, cor `--fraco` ou `--ouro`.
- **Spectral** para texto corrido e narrativa (histórias, descrições).
- **Monoespaçada** só para endereços, comandos e números técnicos.
- Números de placar em Cinzel com `tabular-nums`.

### Forma

- Painéis, cartões, botões e campos: canto de **3px**. Nada de cantos muito
  arredondados.
- Pílula só para chips e filtros; círculo só para marcadores, retratos e o
  relógio do dia.
- Painel: gradiente `168deg` de ardósia translúcida para noite, borda
  `--borda`, sombra funda (`0 22px 60px rgba(0,0,0,.6)`).
- Ornamento dourado nos cantos (filete em L) em painéis de destaque:
  histórias, troféus, perfil. Não em todo cartão.

### Componentes de assinatura

- **Botão principal:** ouro em gradiente vertical, texto escuro, Cinzel
  caixa-alta. **Botão fantasma:** contorno dourado, fundo transparente.
- **Chip de estado:** contorno na cor do estado (bom/neutro/ruim), valor em
  Cinzel.
- **Divisor:** dois filetes com um losango dourado no meio.
- **Switch** para ligar e desligar; nunca checkbox cru. Cada switch tem título
  e uma linha explicando o efeito.
- **Herói com foto:** foto do bioma escurecida por gradiente de `--breu`,
  névoa e brasas só no herói.

### Movimento

Transições curtas (`.15s–.25s`). Brasas, névoa e respiração só em heróis e
sempre desligadas por `prefers-reduced-motion`.

### Acessibilidade

Contraste AA no texto, foco visível dourado (`outline 2px --ouro-claro`),
alvos de toque de 40px ou mais, textos alternativos, layout funcional em
celular sem rolagem horizontal.

## 5. Linguagem de experiência do ValheimSagas, em estilo GenesisMods

- **O mapa é o protagonista.** Ocupa a largura toda, terreno do jogo com névoa
  de exploração, arrastar e dar zoom.
- **Barras flutuantes** sobre o mapa: fundo `--noite` translúcido com
  desfoque, canto 3px, ícones de linha com rótulo (Terreno, Vikings,
  Atividade, Marcadores, Sagas). Zoom `+`/`−`/`Ajustar` num canto.
- **Relógio do dia** circular no canto do mapa: arco do ciclo em ouro, dia no
  centro, "anoitece em…" embaixo.
- **Marcadores** circulares escuros com ícone de linha e aro na cor do tipo;
  chefe com aro dourado e moldura quadrada; grupos em leque.
- **Painel lateral de momento:** arte do chefe ou bioma no topo, rótulo
  ("MOMENTO 2 DE 3"), título em serifa, texto narrativo, bloco "Momento
  registrado" com o fato real, botão fantasma "Ler a saga completa".
- **Replay de jornada:** barra com play, progresso dourado, velocidade e
  "seguir jornada"; linha pontilhada dourada entre os momentos.
- **Perfil do Viking:** cenário do bioma ao fundo, ícones reais dos itens em
  cartões com borda esquerda na cor da raridade, barra rápida numerada
  embaixo. Sem retrato 3D do personagem (decisão de 22/09/2026).
- **Sempre distinguir fato de ficção:** o texto gerado é rotulado como
  ficção e liga aos registros que o inspiraram.

## 6. Recursos opcionais

1. Desligado por padrão, com um switch no Jarl.
2. Cartão "Para funcionar" com a lista de requisitos e seus estados.
3. Ao ligar, o sistema confere o que conseguir e aponta o próximo passo.
4. Desligar interrompe novos registros e oculta o que já existe; retirar
   consentimento apaga.
5. A página pública só mostra a seção quando há dado real; nunca uma seção
   vazia de "em breve".

## 7. Pronto quer dizer

- Testes automatizados passando, incluindo privacidade e limites.
- Compila sem avisos.
- Textos ao usuário revisados pelos pilares 2 e 3.
- Visual conferido contra a seção 4 (tokens, forma, movimento, celular).
- Instruções de atualização e teste completas, executáveis por uma pessoa
  com um cliente, numa VM de teste.
