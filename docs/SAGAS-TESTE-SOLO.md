# Testar Heimdall Sagas com um cliente

Esta é uma prévia de desenvolvimento. Use um servidor e um personagem de teste.
Na VM com o Nexus já instalado, atualize o branch `dev/sagas` antes de rodar
`sudo ./deploy/update.sh`.

## Qual servidor usar?

- **Teste completo do Nexus:** requer Heimdall Nexus instalado no servidor de
  teste, Valheim dedicado e BepInEx no jogo. Mostra Jarl, `/cronicas/` e API.
  O servidor pode não ter nenhum outro mod nem modpack.
- **Teste só da ponte:** requer Valheim dedicado com BepInEx e a DLL Bridge.
  Não requer Nexus, mas produz apenas arquivos JSON na fila local. Não há
  página, API, importador ou controles Jarl. O instalador
  `install-sagas-extension.sh` não funciona nesse modo.

Um Valheim estritamente sem BepInEx não carrega a ponte. O cliente de teste
também precisa de BepInEx e da DLL Client.

## Caminho recomendado: integração completa

1. Prepare uma VM ou máquina de teste Ubuntu/Debian x86-64. Se ainda não houver
   Nexus, use este checkout nela e execute `sudo ./deploy/install.sh`. No
   assistente, habilite **BepInEx** e deixe o modpack vazio. Se já houver
   Nexus nessa máquina, execute `sudo ./deploy/update.sh` a partir deste
   checkout para levar o código da extensão ao runtime. Não execute esses
   passos no servidor de produção.
2. Tenha as duas DLLs compiladas. O comando abaixo usa as bibliotecas de uma
   instalação legal do jogo e do BepInEx; ele gera DLLs e ZIPs locais:

   ```bash
   ./extensoes/sagas/build.sh /caminho/valheim_Data/Managed /caminho/BepInEx/core
   ```

   Se as DLLs deste checkout já foram compiladas, use a Bridge em `dist/sagas/`
   e o ZIP do Client no mesmo diretório.
   Não copie `assembly_valheim.dll` nem bibliotecas do jogo para os ZIPs.
3. Na máquina do Nexus de teste, dentro deste checkout, instale a ponte:

   ```bash
   sudo ./deploy/install-sagas-extension.sh "$(pwd)/dist/sagas/HeimdallSagas.Bridge.dll"
   sudo systemctl restart heimdall-valheim.service
   systemctl is-active heimdall-sagas-ingest.timer
   ```

   O instalador exige um Nexus já instalado, BepInEx no servidor e a DLL
   **Bridge**, não o ZIP. Ele cria a fila privada, configura o serviço de
   importação e a rota pública; o reinício carrega a DLL no Valheim.
4. No computador do jogador, instale BepInEx para Valheim e extraia
   `dist/sagas/HeimdallSagas.Client-0.1.4.zip` na pasta do jogo. O ZIP
   coloca `HeimdallSagas.Client.dll` em
   `BepInEx/plugins/HeimdallSagas/`. Não instale a Bridge no cliente.
5. Abra o jogo uma vez para gerar
   `BepInEx/config/gg.heimdall.sagas.client.cfg`. As opções
   `ShareProfile`, `ShareMap`, `SharePosition` e `ShareStories` começam em `false`.
   Feche e reabra o jogo depois de editar o arquivo.
   Para histórias, ative `ShareProfile` e `ShareStories`. Depois de a presença
   aparecer no Jarl, configure a chave OpenRouter em Sagas e peça um capítulo.
6. Antes de entrar no mundo, confira `/jarl/sagas` no site de teste. Ele deve
   indicar que a DLL da ponte está instalada. Confira também os logs BepInEx
   do servidor para saber se ela carregou. O status do Jarl verifica a
   presença do arquivo; sozinho, ele não prova que o plugin iniciou.
7. Entre com o único cliente. Aguarde até 60 segundos e recarregue
   `/cronicas/` e `/api/sagas/v1/overview`. O dia do mundo pode aparecer sem
   consentimento do jogador. Os testes de perfil, morte, mapa e retirada de
   consentimento seguem no roteiro da conversa.

## Caminho curto: ponte sem Nexus

Instale BepInEx no servidor dedicado e coloque somente a DLL Bridge em
`BepInEx/plugins/HeimdallSagas/`. Crie um diretório `inbox` gravável pelo
usuário que executa o jogo e um arquivo `settings.json` legível por ele:

```json
{"version":1,"enabled":true,"gear":true,"events":true,"clock":true,"kill_mode":"all"}
```

No ambiente do **processo do servidor**, defina caminhos absolutos antes de
iniciá-lo com o seu launcher habitual:

```bash
export HEIMDALL_SAGAS_INBOX=/caminho/privado/sagas/inbox
export HEIMDALL_SAGAS_SETTINGS=/caminho/privado/sagas/settings.json
```

Instale a DLL Client no único cliente e entre no mundo. A ponte deve escrever
arquivos `.json` no `inbox` após o relógio do mundo ou eventos consentidos.
Guarde essa pasta como dado privado. Sem Nexus, nada consumirá os arquivos;
limpe a fila de teste depois de examiná-la. Este caminho confirma o transporte,
mas não valida o site nem a integração com Jarl.
