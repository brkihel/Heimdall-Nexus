# Heimdall Sagas Client

Companheiro do [Heimdall Nexus](https://github.com/brkihel/Heimdall-Nexus) para
o jogador. Ele envia ao site do servidor o perfil do seu Viking, seus grandes
feitos e os momentos no mapa, **somente se você ligar cada opção**.

*English below.*

## Antes de tudo: nada é compartilhado sem você ligar

- Todas as opções de privacidade começam **desligadas**. Instalar o plugin, sozinho, não envia nada.
- Ele só funciona em servidores com a extensão **Heimdall Sagas** do Heimdall Nexus. Nos outros servidores fica inativo.
- Você pode desligar qualquer opção a qualquer momento (veja "Retirar a permissão").

## Como ligar

1. Abra o jogo uma vez com o plugin instalado. Isso cria o arquivo
   `BepInEx/config/gg.heimdall.sagas.client.cfg`.
2. Mude as opções da seção `[Privacy]` que você quiser para `true`:
   - **Com o Configuration Manager** no modpack: aperte **F1** no jogo, procure
     *Heimdall Sagas Client* e ligue as opções ali mesmo.
   - **Sem ele:** feche o jogo, edite o arquivo acima (no Gale ou r2modman:
     *Config editor*) e abra o jogo de novo.

| Opção | O que o site passa a mostrar |
|---|---|
| `ShareProfile` | Seu nome de Viking, presença online, equipamento e feitos registrados. É a base das outras. |
| `ShareMap` | Bioma e local dos seus momentos no mapa do site. Precisa de `ShareProfile`. |
| `SharePosition` | Um marcador ao vivo, só quando o mapa público do próprio Valheim também estiver ligado. |
| `ShareStories` | Seu nome de Viking e alguns feitos compartilhados vão para o provedor de IA escolhido pelo admin do servidor (OpenRouter, OpenAI, Anthropic ou Google Gemini) para escrever histórias públicas. Precisa de `ShareProfile`. |

As histórias são marcadas no site como ficção criada por IA. Coordenadas, IDs
internos, equipamento e mapa **não** são enviados ao provedor de IA.

## Armaria: ícones e retrato

Com `ShareProfile` ligado, a Armaria do site mostra o seu equipamento com os
ícones do jogo, a barra rápida (posições 1 a 8) e um **retrato** do seu Viking
vestido como está agora. O retrato é tirado pelo próprio jogo, uma vez, quando
o visual muda e você está de pé; ele não pesa na partida.

Na seção `[Portrait]`:

| Opção | Para que serve |
|---|---|
| `Enabled` | `false` desliga o retrato; ícones e equipamento continuam. |
| `RefreshKey` | Tecla que tira o retrato de novo na hora (padrão **F9**). |
| `Ambient`, `KeyLight`, `FillLight`, `Reflection` | Luz do estúdio: geral, principal, de preenchimento e brilho do metal. |
| `FieldOfView`, `CameraAngle` | Lente e giro da câmera em volta do Viking. |

Mudou um valor pelo Configuration Manager (F1)? O retrato é refeito na hora,
sem reiniciar o jogo.

## Retirar a permissão

Volte a opção para `false`:
- `ShareProfile`: apaga do site os feitos guardados do seu Viking.
- `ShareMap`: apaga os locais e biomas guardados.
- `ShareStories`: apaga as histórias que citam você.

O site também confere a sua escolha atual a cada visita.

---

## English

Player companion for Heimdall Nexus. It shares your Viking's profile, feats and
map moments with the server's website, **only for the options you turn on**.

- Every privacy option starts **off**; installing the plugin alone sends nothing.
- It only works on servers running the **Heimdall Sagas** extension; elsewhere it stays idle.
- Launch the game once to create `BepInEx/config/gg.heimdall.sagas.client.cfg`,
  then set the `[Privacy]` options you want to `true`: with Configuration
  Manager (F1) in game, or by editing the file while the game is closed.
- `ShareStories` sends your Viking name and selected shared feats to the AI
  provider chosen by the server admin (OpenRouter, OpenAI, Anthropic or Google
  Gemini) for public, AI-labelled stories. Coordinates, internal IDs, equipment
  and map data are never sent to the provider.
- Turning an option back off deletes the matching stored data from the site.
- With `ShareProfile`, the site's Armory shows your equipment with game icons,
  your hotbar (slots 1–8) and a portrait of your Viking, rendered by the game
  when your appearance changes. The `[Portrait]` section turns it off, sets the
  refresh key (F9) and tunes the studio light and camera; any change retakes
  the portrait at once.

The item icon and portrait capture is adapted from Valheim Sagas (MIT); see
THIRD-PARTY-NOTICES.md.
