<div align="center">

<img src=".github/assets/banner.webp" alt="Heimdall Nexus" width="100%">

### O guardião que tudo vê para o seu servidor de Valheim

Instale um servidor dedicado de Valheim, um painel no navegador e um site editável visualmente —<br>
num único assistente guiado, numa máquina nova com Ubuntu ou Debian.

[**Começo rápido**](#começo-rápido) · [**Wiki**](https://github.com/brkihel/Heimdall-Nexus/wiki/Inicio) · [**Read in English**](README.md)

[![Licença](https://img.shields.io/badge/licen%C3%A7a-PolyForm%20Noncommercial-c8a45c?style=flat-square&labelColor=0d151d)](LICENSE)
[![Valheim](https://img.shields.io/badge/Valheim-servidor%20dedicado-c8a45c?style=flat-square&labelColor=0d151d)](https://valheim.com/support/a-guide-to-dedicated-servers/)
[![Plataforma](https://img.shields.io/badge/Ubuntu%20%7C%20Debian-x86--64-c8a45c?style=flat-square&labelColor=0d151d)](#começo-rápido)
[![Python](https://img.shields.io/badge/Python-3.10%2B-c8a45c?style=flat-square&labelColor=0d151d)](https://www.python.org/)

</div>

---

## Instale pelo navegador

O instalador roda no seu servidor e abre no seu navegador. São cinco telas: endereço do site, mundo e senha, mods e dados ao vivo, conta de administrador e revisão. Ele baixa o SteamCMD e o Valheim, instala o BepInEx e o seu modpack se você quiser, e mostra cada etapa enquanto acontece.

<img src=".github/assets/installer.webp" alt="Instalador visual do Heimdall Nexus" width="100%">

## Cuide do servidor por um painel só

Ligue, desligue e reinicie o jogo, acompanhe o log ao vivo, edite arquivos e configurações de mods, instale e atualize mods, agende reinícios e backups e restaure qualquer backup com um clique. Toda mudança fica registrada na auditoria.

<img src=".github/assets/panel.webp" alt="Painel do Heimdall Nexus" width="100%">

## Dê à sua comunidade um site de verdade

Um site rápido com estado do servidor ao vivo, jogadores online, hora do mundo e a lista de mods. Defina nome, logo, favicon e cores em **Aparência**, edite cada texto direto na página e crie páginas a partir dos modelos wiki ou vazio. Sem código e sem planilhas.

<img src=".github/assets/site.webp" alt="Um site de comunidade feito com o Heimdall Nexus" width="100%">

<sub>As capturas usam dados de exemplo.</sub>

## Começo rápido

Numa máquina nova com **Ubuntu ou Debian x86-64** e Python 3.10+:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/brkihel/Heimdall-Nexus.git
cd Heimdall-Nexus
sudo ./deploy/install.sh
```

O terminal mostra um link privado para o instalador. Abra no seu navegador e siga as cinco telas.

| Como abrir o instalador | Quando usar |
|---|---|
| `install.sh` | Padrão. Link HTTPS temporário pela Cloudflare, conferido antes de aparecer. |
| `install.sh --direct` | Máquina numa rede de confiança, como uma VM da sua rede local. Link HTTP para o IP dela. |
| `install.sh --local-only` | Sem serviço externo. Encaminhe a porta com `ssh -L 8765:127.0.0.1:8765 usuario@servidor`. |

Depois entre em `https://seu-dominio/jarl/entrar`. Passo a passo completo: [**Instalação**](https://github.com/brkihel/Heimdall-Nexus/wiki/Instalacao).

## Recursos

<table>
<tr>
<td width="50%" valign="top">

**Servidor de jogo**
- Valheim Dedicated Server pelo SteamCMD, como serviço systemd
- BepInEx opcional, com modpacks da Thunderstore ou do Hexium (é só colar o link)
- Seu próprio modpack `.zip`, com mods privados
- Server Config: nome, mundo, porta, senha, crossplay, argumentos de inicialização

</td>
<td width="50%" valign="top">

**Dia a dia**
- Console ao vivo, gerenciador de arquivos e editor de configurações de mods
- Instalar e atualizar mods, com backup verificado antes de cada mudança
- Tarefas: rotinas cron para reiniciar, ligar, desligar e fazer backup
- Backups para baixar, restaurar, travar e apagar

</td>
</tr>
<tr>
<td width="50%" valign="top">

**Site**
- Estado ao vivo, jogadores, relógio do mundo e lista de mods
- Editor visual com versões e prévias para compartilhar
- Nome, logo, favicon, fundo e uma tabela global de cores
- Páginas a partir dos modelos wiki ou vazio

</td>
<td width="50%" valign="top">

**Seguro por padrão**
- Senha do jogo obrigatória; só pode sair com um mod de servidor sem senha
- Contas Linux separadas para o jogo e o painel
- Links de instalação de uso único; ações privilegiadas passam por um executor auditado
- Sem telemetria: as conexões externas são só os downloads e o link opcional de instalação

</td>
</tr>
</table>

## Documentação

Tudo está na [**wiki**](https://github.com/brkihel/Heimdall-Nexus/wiki/Inicio), em português e inglês:
[Instalação](https://github.com/brkihel/Heimdall-Nexus/wiki/Instalacao) ·
[Configuração](https://github.com/brkihel/Heimdall-Nexus/wiki/Configuracao) ·
[Operação](https://github.com/brkihel/Heimdall-Nexus/wiki/Operacao) ·
[Editor visual](https://github.com/brkihel/Heimdall-Nexus/wiki/Editor-Visual)

## Atualizar

Num servidor já instalado:

```bash
cd ~/Heimdall-Nexus && git pull --ff-only && sudo ./deploy/update.sh
```

Atualiza o painel e as ferramentas sem mexer em mundos, mods ou conteúdo do site, e não reinicia o Valheim.

## Licença

O Heimdall Nexus tem **código aberto para consulta** sob a [PolyForm Noncommercial License 1.0.0](LICENSE). Você pode usar, estudar, modificar e compartilhar para qualquer fim **não comercial**: rodar o seu servidor ou o da sua comunidade, projetos pessoais, estudo e organizações sem fins lucrativos ou públicas. **Vender ou usar comercialmente não é permitido.** Para uso comercial, fale com o autor.

Valheim é marca da Iron Gate AB. As imagens de exemplo em `site/web/assets` vêm do press kit oficial do Valheim e pertencem à Iron Gate AB; elas não fazem parte desta licença. O Heimdall Nexus não é afiliado à Iron Gate AB nem à Coffee Stain.

<div align="center">
<br>
<sub>Feito por <a href="https://github.com/brkihel">BRKiHeL</a> para a comunidade de Valheim.</sub>
</div>
