# Heimdall Nexus

**Valheim Server Management Platform**
Criado por **BRKiHeL**. [Read in English](README.md).

O Heimdall Nexus instala e mantém um servidor dedicado de Valheim, com um painel no navegador e um site público editável visualmente. Pelo painel você cuida do jogo, dos mods, das tarefas agendadas e dos backups. O site já vem com uma identidade neutra do Heimdall: defina nome, logo, favicon, cores, fundo e rodapé em **Aparência**, crie páginas a partir dos modelos wiki ou vazio e edite os textos no editor visual. Sem planilhas nem geradores de página.

## Prepare a VM

Use uma máquina nova com Ubuntu ou Debian x86-64, systemd, Python 3.10 ou mais recente, sudo, internet e espaço para jogo, mundos, mods e backups. Instale primeiro os pacotes do sistema:

~~~bash
sudo apt update
sudo apt install -y git ca-certificates curl tar unzip libc6-i386 lib32gcc-s1 \
  libatomic1 libpulse0 libpulse-dev nginx python3 python3-venv python3-pip rsync
~~~

Se for ativar HTTPS automático, instale também `sudo apt install -y certbot python3-certbot-nginx`. O assistente instala esses pacotes caso faltem, mas prepará-los agora revela problemas no APT antes de você preencher as configurações. SteamCMD, servidor Valheim, BepInEx opcional e arquivos do modpack são baixados pelo assistente. Não é preciso instalar Node.js, Docker nem o cliente Steam. Veja a [preparação completa](docs/wiki/pt-BR/Instalacao.md#1-prepare-a-máquina).

## Instalação visual

Clone o repositório e execute:

~~~bash
git clone https://github.com/brkihel/Heimdall-Nexus.git
cd Heimdall-Nexus
sudo ./deploy/install.sh
~~~

O terminal mostra um link HTTPS temporário para abrir no seu navegador pessoal. O instalador usa o Cloudflare Quick Tunnel; o serviço na VPS continua escutando só em 127.0.0.1:8765. O link termina quando o instalador fecha. Guarde o token em privado. Para dispensar esse serviço externo, rode o modo local na VPS:

~~~bash
sudo ./deploy/install.sh --local-only
~~~

Depois crie o túnel SSH no seu computador:

~~~bash
ssh -L 8765:127.0.0.1:8765 usuario@seu-servidor
~~~

Abra no navegador o link mostrado. Escolha domínio ou IP, nome/mundo/porta do jogo, BepInEx opcional, dados ao vivo, o nome da conta Linux do serviço e o login do painel e se o jogo deve ser iniciado. **Iniciar Valheim vem desmarcado.** A tela mostra o progresso de cada etapa.

O assistente baixa SteamCMD da Valve e instala Valheim Dedicated Server (Steam App 896660), o serviço systemd, pastas persistentes do mundo, Nginx, site e painel. O código dos serviços é copiado para `/opt/heimdall-nexus`, então o painel funciona mesmo que o repositório tenha sido clonado numa pasta pessoal fechada. BepInExPack Valheim é opcional. Selecionar um modpack Hexium traz sua **lista para o site** e pode instalar os pacotes compatíveis com servidor e suas dependências em lote. Se versões requeridas conflitarem, ele usa a mais alta. Pacotes marcados só para cliente são pulados. Confira a configuração de cada mod depois.

Depois, entre em https://SEU-DOMINIO/jarl/entrar ou http://SEU-IP/jarl/entrar sem HTTPS. Edite em **Site → Editor em tela cheia**. As publicações guardam versões e prévias. A cópia editável do site fica em /var/lib/heimdall-nexus/site, separada do repositório.

Com a rede Steam, libere a porta UDP escolhida e a seguinte. O Nginx usa TCP 80 e, com HTTPS, TCP 443. Veja o [guia oficial do servidor Valheim](https://valheim.com/support/a-guide-to-dedicated-servers/).

## Documentação

- [Início da Wiki](docs/wiki/pt-BR/Inicio.md) / [English](docs/wiki/Home.md)
- [Instalação](docs/wiki/pt-BR/Instalacao.md) / [Installation](docs/wiki/Installation.md)
- [Configuração](docs/wiki/pt-BR/Configuracao.md) / [Configuration](docs/wiki/Configuration.md)
- [Operação](docs/wiki/pt-BR/Operacao.md) / [Operations](docs/wiki/Operations.md)
- [Editor visual](docs/wiki/pt-BR/Editor.md) / [Visual editor](docs/wiki/Editor.md)

## Verificações

~~~bash
python3 -m unittest discover -s tests -v
bash -n deploy/install.sh deploy/install-web.sh deploy/valheim-launch.sh
node --check deploy/setup/app.js
~~~

Essas verificações não ligam o Valheim. A instalação completa ainda precisa ser executada de ponta a ponta numa máquina nova; não rode o assistente em servidor de produção existente.
