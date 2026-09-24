# Instalação

[English](../Installation.md) · [Início da Wiki](Inicio.md)

## 1. Prepare a máquina

Use Ubuntu ou Debian x86-64 numa máquina nova, com systemd, sudo, internet e espaço para Valheim, mundos, mods e backups. Confira arquitetura, sistema e espaço livre antes de começar:

~~~bash
uname -m
. /etc/os-release && echo "$PRETTY_NAME"
df -h /
~~~

`uname -m` precisa mostrar `x86_64`. O instalador aceita Ubuntu e Debian e precisa de Python 3.10 ou mais recente; se a VM tiver só a conta root, execute os comandos como root sem `sudo`. Na VM, instale **todos os pacotes de sistema usados pela instalação básica** antes de abrir o assistente:

~~~bash
sudo apt update
sudo apt install -y git ca-certificates curl tar unzip libc6-i386 lib32gcc-s1 \
  libatomic1 libpulse0 libpulse-dev nginx python3 python3-venv python3-pip rsync
python3 --version
~~~

Se for marcar HTTPS automático no assistente, instale também `sudo apt install -y certbot python3-certbot-nginx`. São os mesmos pacotes usados pelo instalador. Ele instala os que faltarem, então repetir não prejudica. Fazer isso antes permite resolver erros do APT sem perder tempo preenchendo o formulário. O [guia oficial do Valheim](https://valheim.com/support/a-guide-to-dedicated-servers/) cita `libatomic1`, `libpulse-dev` e `libpulse0` como dependências de Linux.

**SteamCMD, servidor Valheim, BepInEx opcional e arquivos do modpack são baixados pelo assistente visual.** As bibliotecas do painel são instaladas em um ambiente Python próprio, a partir de `deploy/requirements-panel.txt`. Não precisa instalar Steam, Node.js, Docker nem pacotes Python globalmente.

Mantenha disponíveis DNS, HTTPS de saída, repositórios APT e downloads da Steam. O link temporário do navegador também exige saída para a Cloudflare; o assistente não abre porta de instalação para entrada. Para um site público, aponte um domínio para o IP da VM e libere TCP 80 e 443. HTTPS automático exige DNS público e TCP 80 acessível para emitir o certificado.

Para o jogo, escolha uma porta UDP (padrão 2456). No backend Steam, libere essa porta e a seguinte no firewall e no roteador. O [guia oficial do Valheim](https://valheim.com/support/a-guide-to-dedicated-servers/) explica a rede e o crossplay.

## 2. Baixe o repositório


~~~bash
git clone https://github.com/brkihel/Heimdall-Nexus.git
cd Heimdall-Nexus
./deploy/install.sh --check
~~~

`--check` verifica sistema, arquitetura e conflito com instalação/serviço existente sem alterar a VM. Ele não verifica rede nem executa a instalação completa. Você pode clonar na sua pasta pessoal: durante a instalação, o assistente copia o código usado pelos serviços para `/opt/heimdall-nexus`. A conta do serviço não precisa acessar a sua pasta pessoal. Não inclua senhas, mundos, saves ou arquivos de configuração local no Git.

## 3. Abra o assistente visual

~~~bash
sudo ./deploy/install.sh
~~~

O terminal mostra como abrir o assistente no navegador. São três jeitos:

- **Link HTTPS temporário (padrão).** O instalador cria o link com o Cloudflare Quick Tunnel e só o mostra depois de confirmar que ele abre. Se o link parar de funcionar, ele cria outro e mostra o novo. O assistente continua escutando só em 127.0.0.1:8765.
- **Link direto, `--direct`.** Para uma máquina numa rede de confiança, como uma VM na sua rede local. O assistente escuta no IP da máquina e mostra `http://IP:8765/claim?token=…`. Usa HTTP sem criptografia, então evite em redes públicas. Libere a porta TCP 8765 se o firewall bloquear.
- **Túnel SSH, `--local-only`.** Sem serviço externo e sem porta aberta.

~~~bash
sudo ./deploy/install.sh --direct       # VM na sua rede
sudo ./deploy/install.sh --local-only   # depois, no seu computador:
ssh -L 8765:127.0.0.1:8765 usuario@seu-servidor
~~~

Todo link leva um token de uso único; não o compartilhe. Abra no navegador do seu computador o link completo mostrado no terminal, incluindo o token. Deixe terminal e navegador abertos até a conclusão.

## 4. Preencha as cinco telas

1. **Site:** domínio ou IP e endereço usado pelos jogadores. Ligue HTTPS apenas com domínio DNS público e informe o e-mail do certificado.
2. **Servidor:** nome, mundo, porta UDP, senha opcional do jogo, aparição na lista e crossplay.
3. **Recursos:** marque BepInEx para servidor com mods ou deixe desmarcado para vanilla. O modpack Hexium preenche a lista do site. A opção separada de instalação no servidor baixa as dependências nas versões fixadas e pula pacotes marcados apenas para cliente. Escolha os dados ao vivo disponíveis nesse servidor.
4. **Administrador:** escolha dois nomes separados: a conta Linux que executa o painel (padrão `heimdall`) e o login usado no navegador (padrão `jarl`). Depois defina a senha do painel, guardada como hash. O jogo continua numa conta Linux separada chamada `valheim`.
5. **Revisão:** escolha se Valheim deve iniciar no fim e em cada boot. Vem desmarcado.

A tela de progresso mostra pacotes do sistema, SteamCMD, Valheim App 896660, BepInEx opcional, site/painel e HTTPS. Se uma etapa falhar, corrija a causa e tente novamente no mesmo assistente.

## 5. Comece a usar

Abra os links para site e painel exibidos ao final. Entre no painel e use **Site → Editor em tela cheia** para mudar layout e textos. Se deixou o jogo parado, ligue-o pelo painel quando estiver pronto.

Pastas: /opt/heimdall-nexus para o código instalado dos serviços; /srv/valheim/current para o jogo; /srv/valheim/saves para mundos; /var/lib/heimdall-nexus/site para páginas editáveis; /etc/heimdall-nexus/heimdall.env para dados do host; /etc/heimdall-panel/config.json para a conta do painel. Não apague a pasta de saves ao atualizar o jogo.

## Problemas comuns

- **Não abre o assistente:** confira se o instalador ainda está rodando. Se o link da Cloudflare falhar, o instalador tenta de novo e mostra outro; numa VM da sua rede, rode de novo com `--direct`. Senão, use `--local-only` com túnel SSH.
- **Aparece a página padrão do Nginx ou `/jarl/entrar` dá 404 após instalar:** na VM, rode `sudo nginx -t && sudo systemctl reload nginx`. O Nginx pode estar usando a configuração carregada antes de o instalador criar o site. Confira o painel com `sudo systemctl status heimdall-panel --no-pager`. Nas próximas instalações, o assistente recarrega o Nginx e confere as duas rotas antes de mostrar sucesso.
- **`/jarl/entrar` dá 502 e o painel registra `status=200/CHDIR`:** uma instalação antiga pode ter deixado o código sob uma pasta pessoal inacessível ao serviço. A instalação atual usa `/opt/heimdall-nexus` e evita isso. Para recuperar uma instalação antiga sem reinstalar, entre na pasta do repositório e execute `sudo apt install -y acl`, `sudo setfacl -m u:painel:--x "$HOME" "$PWD" "$PWD/servicos"` e `sudo systemctl restart heimdall-panel`. Isso libera apenas a travessia dessas pastas para `painel`, sem expor a listagem.
- **HTTPS falhou:** confirme DNS e TCP 80. Corrija e tente novamente no mesmo assistente.
- **Servidor não aparece:** confira as portas UDP e se o jogo foi iniciado. Veja os logs com sudo journalctl -u heimdall-valheim -n 100.
- **Servidor continua vanilla:** marque BepInEx e a instalação do modpack no servidor. Veja no progresso os pacotes de cliente pulados e configure os mods necessários.
- **Serviço de jogo já existente:** o assistente não substitui um serviço que não criou. Use uma máquina nova ou faça a migração manual primeiro.

Os testes automáticos ainda não substituem uma instalação completa numa máquina nova. Eles verificam a lógica sem ligar o jogo em produção.
