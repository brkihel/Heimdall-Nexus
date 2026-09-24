# Operação do servidor

## Server Config

Abra **Server Config** no painel para ver os argumentos de inicialização e alterar nome, mundo, porta, visibilidade, crossplay, descrição e senha do jogo. A senha atual nunca é mostrada. Deixe o campo vazio para conservá-la. A senha é obrigatória: só dá para removê-la com um mod de servidor sem senha instalado (por exemplo `serverblankpassword`), e aí aparece a opção **Servidor sem senha**. O Valheim também não aceita a senha dentro do nome do servidor. A descrição é publicada no feed de status do site; o Valheim não oferece uma opção de descrição no comando de partida.

Mudanças dos argumentos entram em vigor após reiniciar o jogo. Quando ele estiver ligado, o painel mostra **Reiniciar para aplicar**. Trocar o nome do mundo pode criar um mundo novo no próximo início; confira o campo antes de salvar. **Reinstalar servidor** exige a senha do administrador do painel, desliga o jogo se estiver ligado e executa a verificação dos arquivos oficiais com SteamCMD. Salvos, configurações e mods permanecem separados. Faça um backup antes. O jogo permanece desligado após a reinstalação.

## Mod Config

**Mod Config** é o antigo editor de configurações dos mods. Os arquivos continuam sob `BepInEx/config`. Muitos mods só leem as opções na partida do jogo; use **Reiniciar servidor** após gravar quando necessário.

## Tarefas

Na aba **Tarefas**, crie uma rotina com nome e cinco campos cron. Depois use **Adicionar tarefa** para incluir, em ordem, o que ela executa; cada tarefa pode esperar alguns segundos antes de rodar. As ações disponíveis são iniciar, desligar, reiniciar e criar backup. Não há execução de comandos arbitrários. O horário segue o fuso configurado no sistema operacional. `0 4 * * *` significa todos os dias às 04:00. **Apenas quando o servidor estiver online** ignora a ocorrência se o jogo estiver desligado; **Rotina ativada** permite pausar sem apagar. O timer `heimdall-schedule.timer` verifica as rotinas uma vez por minuto.

## Backups

**Criar backup agora** faz uma cópia dos salvos, configurações e opções de partida. Se o jogo estiver ligado, ele é desligado para uma cópia consistente e volta depois. A tela permite baixar, restaurar, travar e apagar. Um backup travado não pode ser excluído pelo painel. Antes de restaurar, o sistema cria outro backup do estado atual. Arquivos de manutenção de mods aparecem para download, mas só arquivos de mundo permitem restauração pela tela.

## Repetir a instalação numa VM de teste

O comando abaixo **apaga mundos, backups, site e configurações dessa instalação**. Execute apenas na VM de teste. O repositório Git e os pacotes APT são preservados:

```bash
cd ~/Heimdall-Nexus
sudo ./deploy/reset-vm.sh --check
sudo ./deploy/reset-vm.sh --purge
sudo ./deploy/install.sh
```

O reset funciona numa instalação completa ou numa que parou no meio, e pede a frase `RESET HEIMDALL VM`. Ele remove a conta Linux exclusiva do painel para permitir escolher o mesmo nome novamente; mantém a conta `valheim`.

## Modpack próprio (.zip)

Um servidor com mods que não estão publicados pode usar um modpack em `.zip`, no mesmo formato de pacote do Hexium/Thunderstore:

```
manifest.json          author, name, version_number, description, dependencies
plugins/<Mod>/...      DLLs dos mods próprios ou modificados
patchers/<Mod>/...     patchers do BepInEx, se houver
config/...             configurações (opcional)
```

`dependencies` lista os mods públicos no formato `Autor-Nome-Versão`; eles são baixados do Hexium ou da Thunderstore na instalação. Cada mod incluso fica na própria pasta dentro de `BepInEx/plugins`.

Para gerar o pacote a partir de um servidor já montado:

```bash
sudo python3 ferramentas/criar-modpack.py /var/lib/heimdall-nexus/modpacks/MeuServidor-1.0.0.zip \
  --author MeuTime --name MeuServidor --version 1.0.0
```

O gerador compara cada mod instalado com o pacote oficial da mesma versão. Se todas as DLLs forem idênticas, o mod vira dependência; se não for publicado ou tiver sido modificado, ele vai dentro do `.zip`. Configurações só entram com `--with-config`, e mesmo assim a pasta do AzuAntiCheat e arquivos com nomes como webhook, token ou senha ficam de fora.

Para instalar, envie o `.zip` à VPS e informe o caminho completo (por exemplo `/root/MeuServidor-1.0.0.zip`) no campo Modpack do assistente. O progresso lista o SHA-256 de cada DLL inclusa. Um `.zip` executa código no servidor: use apenas pacotes de origem confiável. Mods que também precisam estar no cliente continuam precisando chegar aos jogadores por outro meio.
