#!/usr/bin/env bash
set -Eeuo pipefail

# Run from an interactive terminal: sudo bash -c "$(curl -fsSL URL)"
REPO_URL="https://github.com/diegogarciarojo/biblioteca-up.git"
INSTALL_DIR="/opt/biblioteca-up"
CONFIG_DIR="/etc/biblioteca-up"
APP_NAME="biblioteca-up-app"
CADDY_NAME="biblioteca-up-caddy"
NETWORK_NAME="biblioteca-up-net"
VOLUME_DATA="biblioteca-up_library_data"
VOLUME_CADDY_DATA="biblioteca-up_caddy_data"
VOLUME_CADDY_CONFIG="biblioteca-up_caddy_config"
MANAGED_LABEL="org.biblioteca-up.managed=true"

say() { printf '\n%s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
trap 'printf "\nLa instalación se detuvo en la línea %s. Revisa el error anterior.\n" "$LINENO" >&2' ERR

[[ "$EUID" -eq 0 ]] || die "Ejecuta el instalador con sudo."
[[ -t 0 ]] || die "Este instalador necesita la entrada de la terminal. Usa el comando actualizado del README."

if [[ ! -r /etc/os-release ]]; then
    die "Este instalador requiere Ubuntu."
fi
. /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || die "Este instalador requiere Ubuntu."

prompt() {
    local answer
    printf '%s' "$1" >&2
    IFS= read -r answer
    printf '%s' "$answer"
}

confirm() {
    local answer
    answer="$(prompt "$1")"
    [[ "$answer" =~ ^([sS]|[sS][iI]|[yY]|[yY][eE][sS])$ ]]
}

confirm_default_yes() {
    local answer
    answer="$(prompt "$1")"
    [[ -z "$answer" || "$answer" =~ ^([sS]|[sS][iI]|[yY]|[yY][eE][sS])$ ]]
}

valid_domain() {
    local name="$1" label
    [[ ${#name} -le 253 && "$name" == *.* && "$name" != *..* ]] || return 1
    [[ "$name" =~ ^[a-z0-9.-]+$ ]] || return 1
    IFS='.' read -r -a labels <<< "$name"
    for label in "${labels[@]}"; do
        [[ ${#label} -ge 1 && ${#label} -le 63 ]] || return 1
        [[ "$label" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || return 1
    done
}

say "Instalación de Biblioteca UP"
USE_DOMAIN=0
DOMAIN=""
CONFIGURE_DYNV6=0
if confirm_default_yes "¿Quieres configurar un dominio con HTTPS? [S/n]: "; then
    USE_DOMAIN=1
    say "Dominio seleccionado. Escribe tu dominio o pulsa Enter para usar biblioteca.dns.army."
    DOMAIN="$(prompt 'Dominio: ')"
    DOMAIN="${DOMAIN:-biblioteca.dns.army}"
    DOMAIN="${DOMAIN,,}"
    valid_domain "$DOMAIN" || die "El dominio no tiene un formato válido. Escribe solo el nombre, sin https:// ni rutas."
fi

say "Preparando Ubuntu..."
packages=()
for package in git curl ca-certificates python3 iproute2; do
    dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed' || packages+=("$package")
done
if (( ${#packages[@]} > 0 )); then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
fi

if ! command -v docker >/dev/null 2>&1; then
    say "Instalando Docker desde su repositorio oficial..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
fi
if ! docker info >/dev/null 2>&1; then
    systemctl start docker 2>/dev/null || true
    docker info >/dev/null 2>&1 || die "Docker está instalado, pero su servicio no responde."
fi
systemctl enable docker >/dev/null 2>&1 || true

for container in "$APP_NAME" "$CADDY_NAME"; do
    if docker container inspect "$container" >/dev/null 2>&1; then
        label="$(docker inspect -f '{{ index .Config.Labels "org.biblioteca-up.managed" }}' "$container")"
        [[ "$label" == "true" ]] || die "Ya existe el contenedor $container y no pertenece a este instalador."
    fi
done

port_busy() {
    local port="$1"
    ss -ltnH | awk '{print $4}' | grep -Eq ":${port}$"
}
if [[ "$(docker inspect -f '{{.State.Running}}' "$CADDY_NAME" 2>/dev/null || true)" != "true" ]]; then
    port_busy 80 && die "El puerto 80 está ocupado. Libéralo antes de instalar (por ejemplo, si lo usa 3x-ui)."
    if (( USE_DOMAIN )); then
        port_busy 443 && die "El puerto 443 está ocupado. Libéralo antes de instalar (por ejemplo, si lo usa 3x-ui)."
    fi
fi

PUBLIC_IP="$(curl -4fsS --max-time 15 https://api.ipify.org)" || die "No pude detectar la IPv4 pública de la VPS."
python3 - "$PUBLIC_IP" <<'PY' || die "La dirección detectada no es una IPv4 pública."
import ipaddress
import sys
address = ipaddress.ip_address(sys.argv[1])
assert isinstance(address, ipaddress.IPv4Address) and address.is_global
PY

if (( USE_DOMAIN )); then
    say "IPv4 pública: $PUBLIC_IP"
    if [[ "$DOMAIN" == *.dns.army || "$DOMAIN" == *.dns.navy || "$DOMAIN" == *.dynv6.net ]]; then
        install -m 0700 -d "$CONFIG_DIR"
        if [[ -s "$CONFIG_DIR/dynv6.token" && -f "$CONFIG_DIR/dynv6.zone" && "$(cat "$CONFIG_DIR/dynv6.zone")" == "$DOMAIN" ]]; then
            CONFIGURE_DYNV6=1
            say "Usaré el token dynv6 guardado para $DOMAIN."
        elif confirm "¿Quieres que actualice automáticamente el DNS de dynv6? Necesitarás el token HTTP de esta zona. [s/N]: "; then
            CONFIGURE_DYNV6=1
            printf 'Token HTTP de dynv6 (entrada oculta): ' >&2
            IFS= read -r -s DYNV6_TOKEN
            printf '\n' >&2
            [[ -n "$DYNV6_TOKEN" ]] || die "El token de dynv6 está vacío."
            umask 077
            printf '%s\n' "$DOMAIN" > "$CONFIG_DIR/dynv6.zone"
            printf '%s\n' "$DYNV6_TOKEN" > "$CONFIG_DIR/dynv6.token"
            unset DYNV6_TOKEN
            chmod 600 "$CONFIG_DIR/dynv6.zone" "$CONFIG_DIR/dynv6.token"
        else
            CONFIGURE_DYNV6=0
        fi
    else
        CONFIGURE_DYNV6=0
    fi
    if (( ! CONFIGURE_DYNV6 )); then
        DNS_IPS="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1}' | sort -u || true)"
        if ! printf '%s\n' "$DNS_IPS" | grep -Fxq "$PUBLIC_IP"; then
            die "El registro A de $DOMAIN no apunta a $PUBLIC_IP. Configúralo en tu proveedor DNS o vuelve a ejecutar el instalador con el token de dynv6."
        fi
    fi
fi

say "Descargando Biblioteca UP..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" pull --ff-only
elif [[ -e "$INSTALL_DIR" ]]; then
    die "$INSTALL_DIR ya existe y no es un clon Git del proyecto."
else
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

if (( USE_DOMAIN && CONFIGURE_DYNV6 )); then
    say "Actualizando dynv6..."
    DNS_UPDATE_PENDING=0
    if python3 "$INSTALL_DIR/scripts/update_dynv6.py" "$PUBLIC_IP"; then
        :
    else
        update_status=$?
        if [[ "$update_status" == "2" ]]; then
            die "dynv6 rechazó el token HTTP. Corrige $CONFIG_DIR/dynv6.token y repite el instalador."
        fi
        DNS_UPDATE_PENDING=1
        say "Continuaré la instalación; dynv6 se volverá a intentar automáticamente cada 10 minutos."
    fi
    cat > /etc/systemd/system/biblioteca-up-dynv6.service <<EOF
[Unit]
Description=Actualizar IPv4 de dynv6 para Biblioteca UP
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $INSTALL_DIR/scripts/update_dynv6.py
EOF
    cat > /etc/systemd/system/biblioteca-up-dynv6.timer <<'EOF'
[Unit]
Description=Comprobar la IPv4 de dynv6 cada 10 minutos

[Timer]
OnBootSec=2min
OnUnitActiveSec=10min
Persistent=true

[Install]
WantedBy=timers.target
EOF
    chmod 644 /etc/systemd/system/biblioteca-up-dynv6.service /etc/systemd/system/biblioteca-up-dynv6.timer
    systemctl daemon-reload
    systemctl enable --now biblioteca-up-dynv6.timer
elif systemctl list-unit-files biblioteca-up-dynv6.timer --no-legend 2>/dev/null | grep -q '^biblioteca-up-dynv6.timer'; then
    systemctl disable --now biblioteca-up-dynv6.timer
fi

ENV_FILE="$INSTALL_DIR/.env"
SECRET=""
MAX_PDF_MB=1024
if [[ -f "$ENV_FILE" ]]; then
    SECRET="$(sed -n 's/^DJANGO_SECRET_KEY=//p' "$ENV_FILE" | head -n 1)"
    old_limit="$(sed -n 's/^MAX_PDF_MB=//p' "$ENV_FILE" | head -n 1)"
    [[ "$old_limit" =~ ^[1-9][0-9]*$ ]] && MAX_PDF_MB="$old_limit"
fi
SECRET="${SECRET:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')}"
if (( USE_DOMAIN )); then
    HOSTS="$DOMAIN,localhost,127.0.0.1"
    ORIGINS="https://$DOMAIN"
    HTTPS=1
    SITE_ADDRESS="$DOMAIN"
    PUBLIC_URL="https://$DOMAIN"
else
    HOSTS="$PUBLIC_IP,localhost,127.0.0.1"
    ORIGINS="http://$PUBLIC_IP"
    HTTPS=0
    SITE_ADDRESS="http://:80"
    PUBLIC_URL="http://$PUBLIC_IP"
fi
umask 077
cat > "$ENV_FILE.tmp" <<EOF
DJANGO_SECRET_KEY=$SECRET
DJANGO_DEBUG=0
DJANGO_USE_HTTPS=$HTTPS
DJANGO_ALLOWED_HOSTS=$HOSTS
DJANGO_CSRF_TRUSTED_ORIGINS=$ORIGINS
MAX_PDF_MB=$MAX_PDF_MB
EOF
mv -f "$ENV_FILE.tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"

cat > "$INSTALL_DIR/deploy/Caddyfile.runtime" <<EOF
$SITE_ADDRESS {
    encode zstd gzip
    request_body {
        max_size 1100MB
    }
    reverse_proxy $APP_NAME:8000
}
EOF
chmod 644 "$INSTALL_DIR/deploy/Caddyfile.runtime"

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
    ufw allow 80/tcp
    if (( USE_DOMAIN )); then ufw allow 443/tcp; fi
fi

say "Construyendo la aplicación y preparando Caddy..."
docker build -t biblioteca-up:local "$INSTALL_DIR"
docker pull caddy:2.11.4-alpine
docker run --rm -v "$INSTALL_DIR/deploy/Caddyfile.runtime:/etc/caddy/Caddyfile:ro" \
    caddy:2.11.4-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker network inspect "$NETWORK_NAME" >/dev/null 2>&1 || docker network create "$NETWORK_NAME" >/dev/null
for volume in "$VOLUME_DATA" "$VOLUME_CADDY_DATA" "$VOLUME_CADDY_CONFIG"; do
    docker volume create "$volume" >/dev/null
done

for container in "$CADDY_NAME" "$APP_NAME"; do
    if docker container inspect "$container" >/dev/null 2>&1; then
        docker rm -f "$container" >/dev/null
    fi
done

say "Iniciando Biblioteca UP..."
docker run -d --name "$APP_NAME" --label "$MANAGED_LABEL" \
    --restart unless-stopped --network "$NETWORK_NAME" \
    --env-file "$ENV_FILE" -e BIBLIOTECA_DATA_DIR=/data \
    -v "$VOLUME_DATA:/data" biblioteca-up:local >/dev/null

ready=0
for _ in {1..45}; do
    if docker exec "$APP_NAME" python3 -c "import urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/health/', headers={'X-Forwarded-Proto': 'https'}), timeout=3).read()" >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 2
done
if (( ! ready )); then
    docker logs --tail 80 "$APP_NAME" >&2
    die "La aplicación no respondió a tiempo."
fi

caddy_ports=(-p 80:80)
if (( USE_DOMAIN )); then caddy_ports+=(-p 443:443); fi
docker run -d --name "$CADDY_NAME" --label "$MANAGED_LABEL" \
    --restart unless-stopped --network "$NETWORK_NAME" \
    "${caddy_ports[@]}" \
    -v "$INSTALL_DIR/deploy/Caddyfile.runtime:/etc/caddy/Caddyfile:ro" \
    -v "$VOLUME_CADDY_DATA:/data" -v "$VOLUME_CADDY_CONFIG:/config" \
    caddy:2.11.4-alpine >/dev/null
sleep 2
if [[ "$(docker inspect -f '{{.State.Running}}' "$CADDY_NAME")" != "true" ]]; then
    docker logs --tail 80 "$CADDY_NAME" >&2
    die "Caddy no pudo iniciar."
fi

if ! docker exec "$APP_NAME" python manage.py shell -c \
    'from django.contrib.auth import get_user_model; import sys; sys.exit(0 if get_user_model().objects.filter(is_superuser=True).exists() else 1)' >/dev/null 2>&1; then
    say "Crea ahora el usuario y la contraseña del administrador:"
    docker exec -it "$APP_NAME" python manage.py createsuperuser
fi

say "Biblioteca UP está instalada: $PUBLIC_URL"
say "Administración: $PUBLIC_URL/login"
if (( USE_DOMAIN )); then
    say "Caddy solicitará y renovará el certificado HTTPS automáticamente. Abre TCP 80 y 443 en el Security Group de AWS."
    if (( ${DNS_UPDATE_PENDING:-0} )); then
        say "El DNS aún no se actualizó. HTTPS quedará pendiente hasta que dynv6 responda y el registro A apunte a $PUBLIC_IP."
    fi
else
    say "Sin dominio, el acceso es por HTTP. Puedes repetir el instalador más tarde para activar HTTPS con un dominio."
fi
say "Estado: docker ps --filter label=org.biblioteca-up.managed=true"
