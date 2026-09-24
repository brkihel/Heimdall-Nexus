#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Instala o site e o painel em Ubuntu/Debian. Etapa interna do Heimdall Nexus.

Uso interno: sudo deploy/install-web.sh --domain exemplo.org [opções]
  --domain DOMINIO          Nome DNS do site
  --server-address HOST     Endereço de jogo mostrado na página (padrão: domínio)
  --server-ip IP            IP de reserva mostrado junto ao endereço (opcional)
  --root CAMINHO            Checkout do projeto (padrão: raiz deste script)
  --web-root CAMINHO         Arquivos publicados (padrão: /srv/heimdall-web)
  --valheim-root CAMINHO     Raiz do servidor Valheim (padrão: /srv/valheim)
  --world-name NOME          Nome do mundo salvo (padrão: Valheim)
  --server-name NOME         Nome do servidor no jogo (padrão: Valheim)
  --server-port PORTA        Porta UDP do jogo (padrão: 2456)
  --panel-os-user NOME       Conta Linux do serviço do painel (padrão: heimdall)
  --modpack AUTOR/NOME       Modpack do Hexium, ou none para servidor sem modpack
  --features LISTA           servidor,jogadores,mundo,estacoes,recursos,saga (ou none)
  --cookie-secure true|false Cookies seguros quando HTTPS está ativo (padrão: true)
  --no-start                 Prepara serviços; o assistente os inicia após configurar a senha
  --dry-run                  Mostra o plano, sem alterar o sistema
  -h, --help                 Esta ajuda

O script instala dependências, cria usuários e serviços do painel, configura o
Nginx em HTTP e publica o site. Ele não habilita o serviço heimdall-valheim do jogo.
Configure HTTPS com Certbot depois que o DNS apontar para esta máquina.
EOF
}

DOMAIN=""
SERVER_ADDRESS=""
SERVER_IP=""
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_ROOT="/srv/heimdall-web"
VALHEIM_ROOT="/srv/valheim"
WORLD_NAME="Valheim"
SERVER_NAME="Valheim"
SERVER_PORT="2456"
MODPACK="none"
PANEL_OS_USER="heimdall"
SITE_DIR="/var/lib/heimdall-nexus/site"
DATA_DIR="/var/lib/heimdall-nexus/dados"
FEATURES="servidor,jogadores,mundo,estacoes,saga"
DRY_RUN=0
NO_START=0
COOKIE_SECURE="true"
while (($#)); do
  case "$1" in
    --domain) DOMAIN="${2:?domínio obrigatório}"; shift 2 ;;
    --server-address) SERVER_ADDRESS="${2:?endereço obrigatório}"; shift 2 ;;
    --server-ip) SERVER_IP="${2:?IP obrigatório}"; shift 2 ;;
    --root) ROOT="${2:?caminho obrigatório}"; shift 2 ;;
    --web-root) WEB_ROOT="${2:?caminho obrigatório}"; shift 2 ;;
    --valheim-root) VALHEIM_ROOT="${2:?caminho obrigatório}"; shift 2 ;;
    --world-name) WORLD_NAME="${2:?nome obrigatório}"; shift 2 ;;
    --server-name) SERVER_NAME="${2:?nome obrigatório}"; shift 2 ;;
    --server-port) SERVER_PORT="${2:?porta obrigatória}"; shift 2 ;;
    --panel-os-user) PANEL_OS_USER="${2:?nome obrigatório}"; shift 2 ;;
    --modpack) MODPACK="${2:?use autor/nome ou none}"; shift 2 ;;
    --features) FEATURES="${2:?lista obrigatória}"; shift 2 ;;
    --cookie-secure) COOKIE_SECURE="${2:?true ou false}"; shift 2 ;;
    --no-start) NO_START=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Opção desconhecida: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$DOMAIN" || ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "Informe --domain com um domínio válido." >&2; exit 2
fi
SERVER_ADDRESS="${SERVER_ADDRESS:-$DOMAIN}"
if [[ ! "$SERVER_ADDRESS" =~ ^[A-Za-z0-9.-]+$ ]]; then echo "--server-address inválido." >&2; exit 2; fi
if [[ -n "$SERVER_IP" && ! "$SERVER_IP" =~ ^[A-Fa-f0-9:.]+$ ]]; then echo "--server-ip inválido." >&2; exit 2; fi
if [[ ! "$WORLD_NAME" =~ ^[A-Za-z0-9_\ -]{1,40}$ ]]; then echo "--world-name aceita letras, números, espaço, hífen e _." >&2; exit 2; fi
if [[ ! "$SERVER_NAME" =~ ^[A-Za-z0-9_.\ -]{1,60}$ ]]; then echo "--server-name aceita letras, números, espaço, ponto, hífen e _." >&2; exit 2; fi
if [[ ! "$SERVER_PORT" =~ ^[0-9]{4,5}$ ]] || ((10#$SERVER_PORT < 1024 || 10#$SERVER_PORT > 65534)); then
  echo "--server-port deve estar entre 1024 e 65534." >&2; exit 2
fi
if [[ "$COOKIE_SECURE" != true && "$COOKIE_SECURE" != false ]]; then echo "--cookie-secure deve ser true ou false." >&2; exit 2; fi
if [[ ! "$PANEL_OS_USER" =~ ^[a-z_][a-z0-9_-]{2,30}$ || "$PANEL_OS_USER" == root || "$PANEL_OS_USER" == valheim || "$PANEL_OS_USER" == www-data || "$PANEL_OS_USER" == nobody || "$PANEL_OS_USER" == daemon ]]; then
  echo "--panel-os-user inválido ou reservado." >&2; exit 2
fi
if [[ ! -f "$ROOT/servicos/painel/app.py" || ! -f "$ROOT/site/web/publicar.py" ]]; then
  echo "--root não parece ser a raiz do Heimdall Nexus: $ROOT" >&2; exit 2
fi
if [[ "$MODPACK" != "none" && ! "$MODPACK" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "--modpack deve ser autor/nome ou none." >&2; exit 2
fi
for feature in ${FEATURES//,/ }; do
  case "$feature" in servidor|jogadores|mundo|estacoes|recursos|saga) ;;
    none) FEATURES="" ;;
    *) echo "Recurso desconhecido: $feature" >&2; exit 2 ;;
  esac
done

plan() {
  cat <<EOF
Instalação planejada
  domínio:       $DOMAIN
  endereço jogo: $SERVER_ADDRESS${SERVER_IP:+ (reserva $SERVER_IP)}
  código:        $ROOT
  conta Linux:  $PANEL_OS_USER (painel web)
  site publicado: $WEB_ROOT
  conteúdo editável: $SITE_DIR (separado do código instalado)
  Valheim:       $VALHEIM_ROOT
  mundo salvo:   $WORLD_NAME
  servidor:      $SERVER_NAME (UDP $SERVER_PORT)
  modpack:       $MODPACK
  dados ao vivo: ${FEATURES:-nenhum}
  serviços web:  heimdall-executor, heimdall-panel, heimdall-schedule.timer, nginx
  iniciar web:   $([[ "$NO_START" == 1 ]] && echo não || echo sim)
EOF
}
plan
((DRY_RUN)) && exit 0

if ((EUID != 0)); then echo "Execute com sudo." >&2; exit 1; fi
if [[ ! -r /etc/os-release ]]; then echo "Não identifiquei a distribuição." >&2; exit 1; fi
. /etc/os-release
if [[ "${ID:-}" != ubuntu && "${ID:-}" != debian ]]; then
  echo "Esta versão do instalador aceita Ubuntu e Debian; detectei ${PRETTY_NAME:-desconhecido}." >&2; exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y nginx python3 python3-venv python3-pip rsync

install -d -o root -g root -m 0755 /etc/heimdall-nexus
PANEL_ACCOUNT_MARKER=/etc/heimdall-nexus/panel-os-user
if [[ -e "$PANEL_ACCOUNT_MARKER" ]]; then
  if [[ "$(cat "$PANEL_ACCOUNT_MARKER")" != "$PANEL_OS_USER" ]]; then
    echo "A instalação parcial já usa outra conta Linux; mantenha a conta escolhida antes." >&2; exit 1
  fi
elif id "$PANEL_OS_USER" >/dev/null 2>&1 || getent group "$PANEL_OS_USER" >/dev/null; then
  echo "A conta ou grupo Linux $PANEL_OS_USER já existe e não foi criado por este instalador." >&2; exit 1
else
  # Record the choice before account creation so a partial install can retry.
  printf '%s\n' "$PANEL_OS_USER" > "$PANEL_ACCOUNT_MARKER"
  chmod 0644 "$PANEL_ACCOUNT_MARKER"
fi
getent group "$PANEL_OS_USER" >/dev/null || groupadd --system "$PANEL_OS_USER"
id "$PANEL_OS_USER" >/dev/null 2>&1 || useradd --system --gid "$PANEL_OS_USER" --home-dir /var/lib/heimdall-panel \
  --create-home --shell /usr/sbin/nologin "$PANEL_OS_USER"
usermod -a -G www-data "$PANEL_OS_USER"
chown root:"$PANEL_OS_USER" /etc/heimdall-nexus
chmod 0750 /etc/heimdall-nexus
install -d -o "$PANEL_OS_USER" -g "$PANEL_OS_USER" -m 0750 /var/lib/heimdall-panel/troca
install -d -o root -g "$PANEL_OS_USER" -m 0750 /var/log/heimdall-panel
install -d -o www-data -g www-data -m 0755 "$WEB_ROOT/api"
install -d -o www-data -g www-data -m 0755 "$WEB_ROOT/assets"
install -d -o www-data -g www-data -m 0755 /var/backups/heimdall-web
install -d -o root -g root -m 0750 /var/backups/heimdall-panel
install -d -o root -g root -m 0755 /var/lib/heimdall-nexus
install -d -o root -g "$PANEL_OS_USER" -m 0750 "$SITE_DIR" "$DATA_DIR/catalogs" "$DATA_DIR/downloads"
if [[ ! -e "$SITE_DIR/.heimdall-instance" ]]; then
  rsync -a --exclude='__pycache__/' --exclude='*.pyc' --exclude='mods.json' \
    --exclude='assets/mods/*.webp' "$ROOT/site/web/" "$SITE_DIR/"
  # First identity of the site: the server name chosen in the wizard and the
  # public address. Everything else is edited later in Panel > Aparência.
  python3 - "$SITE_DIR" "$SERVER_NAME" "$DOMAIN" "$COOKIE_SECURE" "$SERVER_ADDRESS" "$SERVER_PORT" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
name, domain, https, address, port = sys.argv[2:]
sys.path.insert(0, str(root))
import identidade
ident = identidade.carregar(root)
ident['nome'] = name[:60] or ident['nome']
ident['url'] = ('https://' if https == 'true' else 'http://') + domain
ident = identidade.validar(ident)
(root / identidade.ARQUIVO).write_text(json.dumps(ident, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
manifest = json.loads((root / 'site-pages.json').read_text(encoding='utf-8'))
sources = [p['fonte'] for p in manifest['paginas']] + [t['modelo'] for t in manifest.get('tipos', {}).values()]
for relative in sources:
    path = root / relative
    text = identidade.aplicar(path.read_text(encoding='utf-8'), ident)
    text = text.replace('seu-servidor.example.com', address).replace(':2456', ':' + port)
    path.write_text(text, encoding='utf-8')
PY
  touch "$SITE_DIR/.heimdall-instance"
fi
if [[ ! -e /etc/heimdall-nexus/modpack.json ]]; then
  python3 - "$MODPACK" "$SITE_DIR/descricoes-pt.json" > /etc/heimdall-nexus/modpack.json <<'PY'
import json, sys
print(json.dumps({'package': '' if sys.argv[1] == 'none' else sys.argv[1],
                  'description_overrides': sys.argv[2]}, ensure_ascii=False, indent=2))
PY
  chown root:"$PANEL_OS_USER" /etc/heimdall-nexus/modpack.json
  chmod 0640 /etc/heimdall-nexus/modpack.json
fi
# Runtime helpers can be upgraded from code; editable HTML and JSON data above
# remain instance-owned and are never overwritten by rerunning the installer.
install -D -m 0640 "$ROOT/site/web/publicar.py" "$SITE_DIR/publicar.py"
install -D -m 0640 "$ROOT/site/web/values.py" "$SITE_DIR/values.py"
install -D -m 0640 "$ROOT/site/web/sync_modpack.py" "$SITE_DIR/sync_modpack.py"
install -D -m 0640 "$ROOT/site/web/identidade.py" "$SITE_DIR/identidade.py"
for template in "$ROOT"/site/web/modelos-pagina/*.html; do
  [[ -e "$SITE_DIR/modelos-pagina/$(basename "$template")" ]] || \
    install -D -m 0640 "$template" "$SITE_DIR/modelos-pagina/$(basename "$template")"
done
[[ -e "$SITE_DIR/marca/favicon.svg" ]] || install -D -m 0640 "$ROOT/site/web/marca/favicon.svg" "$SITE_DIR/marca/favicon.svg"
for asset in vivo.js modpack.js mod-placeholder.svg; do
  install -D -m 0644 "$ROOT/site/web/assets/$asset" "$SITE_DIR/assets/$asset"
done
for catalog in hexium thunderstore; do
  if [[ ! -e "$DATA_DIR/catalogs/$catalog.json" ]]; then
    printf '[]\n' > "$DATA_DIR/catalogs/$catalog.json"
  fi
done
chown root:"$PANEL_OS_USER" "$DATA_DIR/catalogs/hexium.json" "$DATA_DIR/catalogs/thunderstore.json"
chmod 0640 "$DATA_DIR/catalogs/hexium.json" "$DATA_DIR/catalogs/thunderstore.json"
if [[ "$MODPACK" == "none" ]]; then
  if [[ ! -e "$SITE_DIR/mods.json" ]]; then
    printf '{"modpack":"","modpack_owner":"","versao_pack":"","total":0,"mods":[]}\n' > "$SITE_DIR/mods.json"
  fi
else
  python3 "$SITE_DIR/sync_modpack.py" --config /etc/heimdall-nexus/modpack.json \
    --output "$SITE_DIR/mods.json" --apply
fi
if [[ ! -e "$SITE_DIR/descricoes-pt.json" ]]; then
  printf '{}\n' > "$SITE_DIR/descricoes-pt.json"
fi
chown -R root:"$PANEL_OS_USER" "$SITE_DIR" "$DATA_DIR"
chmod -R g+rX,g-w,o-rwx "$SITE_DIR" "$DATA_DIR"

ENV_FILE=/etc/heimdall-nexus/heimdall.env
if [[ ! -e "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<EOF
HEIMDALL_ROOT=$ROOT
HEIMDALL_SITE_DIR=$SITE_DIR
HEIMDALL_DATA_DIR=$DATA_DIR
HEIMDALL_VALHEIM_DIR=$VALHEIM_ROOT
HEIMDALL_WEB_DIR=$WEB_ROOT
HEIMDALL_STATE_DIR=/var/lib/heimdall-nexus
HEIMDALL_PANEL_STATE_DIR=/var/lib/heimdall-panel
HEIMDALL_PANEL_SWAP_DIR=/var/lib/heimdall-panel/troca
HEIMDALL_PANEL_SOCKET=/run/heimdall-panel/executor.sock
HEIMDALL_GAME_SERVICE=heimdall-valheim
HEIMDALL_PANEL_AUDIT_FILE=/var/log/heimdall-panel/auditoria.jsonl
HEIMDALL_PANEL_BACKUP_DIR=/var/backups/heimdall-panel
HEIMDALL_WEB_BACKUP_DIR=/var/backups/heimdall-web
HEIMDALL_CHRONICLE_DIR=/var/lib/heimdall-nexus/cronica
HEIMDALL_PROFILES_DIR=/var/lib/heimdall-nexus/perfis
HEIMDALL_MODS_LOCK=$VALHEIM_ROOT/current/mods.lock.json
HEIMDALL_STATUS_FILE=$WEB_ROOT/api/status.json
HEIMDALL_SAGA_FILE=$WEB_ROOT/api/saga.json
HEIMDALL_LOCATIONS_FILE=$WEB_ROOT/mapa/locais.json
HEIMDALL_GAME_SERVICE_FILE=/etc/systemd/system/heimdall-valheim.service
HEIMDALL_WORLD_NAME=$WORLD_NAME
HEIMDALL_SERVER_NAME=$SERVER_NAME
HEIMDALL_SERVER_ADDRESS=$SERVER_ADDRESS
HEIMDALL_SERVER_IP=$SERVER_IP
HEIMDALL_SERVER_PORT=$SERVER_PORT
HEIMDALL_TIMEZONE=UTC
HEIMDALL_PANEL_COOKIE_SECURE=$COOKIE_SECURE
HEIMDALL_PANEL_OS_USER=$PANEL_OS_USER
HEIMDALL_WEB_USER=www-data
PAINEL_RAIZ=/jarl
PAINEL_CONFIG=/etc/heimdall-panel/config.json
EOF
  chown root:"$PANEL_OS_USER" "$ENV_FILE"; chmod 0640 "$ENV_FILE"
else
  echo "Mantive a configuração existente em $ENV_FILE; confira os caminhos antes de continuar."
fi

if [[ ! -e /etc/heimdall-panel/config.json ]]; then
  install -d -o "$PANEL_OS_USER" -g "$PANEL_OS_USER" -m 0750 /etc/heimdall-panel
  printf '{"usuario":"jarl"}\n' > /etc/heimdall-panel/config.json
  chown "$PANEL_OS_USER":"$PANEL_OS_USER" /etc/heimdall-panel/config.json
  chmod 0600 /etc/heimdall-panel/config.json
fi

if [[ ! -x "$ROOT/servicos/painel/.venv/bin/uvicorn" ]]; then
  python3 -m venv "$ROOT/servicos/painel/.venv"
  "$ROOT/servicos/painel/.venv/bin/pip" install --upgrade pip
  "$ROOT/servicos/painel/.venv/bin/pip" install -r "$ROOT/deploy/requirements-panel.txt"
fi
chown -R root:"$PANEL_OS_USER" "$ROOT/servicos/painel"
chmod -R g+rX,g-w,o-rwx "$ROOT/servicos/painel"
if ! runuser -u "$PANEL_OS_USER" -- sh -c 'cd "$1" && test -r app.py && test -x .venv/bin/uvicorn' sh "$ROOT/servicos/painel"; then
  echo "O usuário $PANEL_OS_USER não consegue acessar o executável do painel em $ROOT/servicos/painel." >&2
  echo "Confira as permissões com: namei -l $ROOT/servicos/painel/.venv/bin/uvicorn" >&2
  echo "Execute o assistente visual a partir do checkout; ele instala o código em /opt/heimdall-nexus." >&2
  exit 1
fi

if [[ ! -e "$WEB_ROOT/api/status.json" ]]; then
  printf '{"online":false,"servidor":{},"jogadores":{}}\n' > "$WEB_ROOT/api/status.json"
  chown www-data:www-data "$WEB_ROOT/api/status.json"
fi
if [[ ! -e "$WEB_ROOT/api/saga.json" ]]; then
  printf '{"total_vikings":0,"jogadores":[]}\n' > "$WEB_ROOT/api/saga.json"
  chown www-data:www-data "$WEB_ROOT/api/saga.json"
fi
python3 - "$WEB_ROOT/api/features.json" "$FEATURES" <<'PY'
import json, sys
path, raw = sys.argv[1:]
features = [] if raw == 'none' or not raw else [x for x in raw.split(',') if x]
with open(path, 'w', encoding='utf-8') as f:
    json.dump({'enabled': features}, f)
    f.write('\n')
PY
chown www-data:www-data "$WEB_ROOT/api/features.json"
if [[ -d "$SITE_DIR/assets" ]]; then
  rsync -a "$SITE_DIR/assets/" "$WEB_ROOT/assets/"
  chown -R www-data:www-data "$WEB_ROOT/assets"
fi

python3 - "$ROOT/deploy/systemd" "$ROOT" "$WEB_ROOT" "$DATA_DIR" "$SITE_DIR" "$PANEL_OS_USER" <<'PY'
from pathlib import Path
import sys
source, root, web, data, site, panel_user = Path(sys.argv[1]), *sys.argv[2:]
replacements = {'@ROOT@': root, '@WEB_ROOT@': web, '@STATE_ROOT@': '/var/lib/heimdall-nexus',
                '@PANEL_SWAP_DIR@': '/var/lib/heimdall-panel/troca',
                '@PANEL_OS_USER@': panel_user}
names = ('heimdall-executor.service', 'heimdall-panel.service',
         'heimdall-status.service', 'heimdall-status.timer',
         'heimdall-saga.service', 'heimdall-saga.timer',
         'heimdall-schedule.service', 'heimdall-schedule.timer')
dest = Path('/etc/systemd/system')
for name in names:
    text = (source / name).read_text()
    for key, value in replacements.items():
        text = text.replace(key, value)
    (dest / name).write_text(text)
    (dest / name).chmod(0o644)
PY
python3 - "$ROOT/deploy/nginx/heimdall-nexus.conf.template" "/etc/nginx/sites-available/heimdall-nexus" "$DOMAIN" "$WEB_ROOT" <<'PY'
from pathlib import Path
import sys
template, output, domain, webroot = sys.argv[1:]
text = Path(template).read_text()
text = text.replace('@DOMAIN@', domain).replace('@WEB_ROOT@', webroot)
Path(output).write_text(text)
PY
ln -sfn /etc/nginx/sites-available/heimdall-nexus /etc/nginx/sites-enabled/heimdall-nexus
rm -f /etc/nginx/sites-enabled/default
nginx -t

HEIMDALL_WEB_DIR="$WEB_ROOT" HEIMDALL_WEB_USER=www-data HEIMDALL_WEB_BACKUP_DIR=/var/backups/heimdall-web \
  HEIMDALL_SITE_DIR="$SITE_DIR" python3 "$SITE_DIR/publicar.py"
systemctl daemon-reload
if (( ! NO_START )); then
  systemctl enable --now heimdall-executor.service heimdall-panel.service heimdall-schedule.timer nginx.service
  if [[ ",$FEATURES," == *",servidor,"* || ",$FEATURES," == *",jogadores,"* || ",$FEATURES," == *",mundo,"* || ",$FEATURES," == *",estacoes,"* || ",$FEATURES," == *",recursos,"* ]]; then
    systemctl enable --now heimdall-status.timer
  fi
  if [[ ",$FEATURES," == *",saga,"* ]]; then systemctl enable --now heimdall-saga.timer; fi
  systemctl reload nginx
fi

cat <<EOF

Configuração do site e painel concluída.
  Site: http://$DOMAIN/
  Painel: http://$DOMAIN/jarl/entrar
  Configure a senha: sudo $ROOT/servicos/painel/.venv/bin/python $ROOT/servicos/painel/definir-senha.py

O serviço heimdall-valheim (jogo) é preparado pelo assistente visual em outra etapa.
EOF
