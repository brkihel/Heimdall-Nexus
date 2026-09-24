# Configuração

[English](../Configuration.md) · [Início da Wiki](Inicio.md)

## Jogo e painel

O instalador escreve as opções de partida em /srv/valheim/server.env e cria heimdall-valheim.service. O painel usa esse serviço para ligar e parar o Valheim. Os mundos ficam em /srv/valheim/saves, separados das atualizações do SteamCMD. As opções de site, painel e coletores ficam em /etc/heimdall-nexus/heimdall.env. A conta do painel fica em /etc/heimdall-panel/config.json.

Se o servidor aceitar jogadores, mas não responder à consulta local de status UDP (A2S), o painel usa a mensagem `Game server connected` da execução atual para indicar que está no ar. Nesse caso, o número de jogadores fica indisponível (`—`) e o horário do mundo mostra o último save, sem afirmar que não há ninguém jogando. A senha do jogo pode ser consultada localmente com `sudo grep '^VH_PASSWORD=' /srv/valheim/server.env`; não compartilhe essa saída.

Use o painel no dia a dia. Se alterar uma configuração de sistema manualmente, reinicie somente o serviço web ou coletor afetado. Atualizações futuras devem preservar as pastas de dados da instalação.

## Dados ao vivo

O editor oferece valores arrastáveis. Estado do servidor, jogadores e mundo podem ser usados em servidor vanilla. Estações e saga exigem o mod ou a fonte correspondente. Quando falta uma fonte, aparece um marcador; escolha os grupos apropriados. Os grupos escolhidos são registrados em /api/features.json.

## Lista do modpack

A página inicial lê mods.json. Ao selecionar um pacote Hexium, o instalador importa sua lista para o site. A escolha separada de instalar no servidor baixa o pacote e suas dependências fixadas para o BepInEx, pulando pacotes explicitamente marcados só para cliente. O painel lê o mods.lock.json resultante. Alguns mods exigem configuração adicional. Para revisar uma atualização posterior **da lista do site** antes de aplicá-la:

~~~bash
sudo python3 /var/lib/heimdall-nexus/site/sync_modpack.py --config /etc/heimdall-nexus/modpack.json
~~~

Depois de ver as diferenças, use --apply e publique os dados de mods pelo painel. Descrições manuais são preservadas no arquivo de substituições configurado. Você também pode manter a lista manualmente.

## Conteúdo

Um site novo começa com textos de exemplo, o favicon do Heimdall e uma paleta neutra. Defina a identidade em **Aparência** e os textos no [editor visual](Editor.md). Publicar páginas não executa geradores.
