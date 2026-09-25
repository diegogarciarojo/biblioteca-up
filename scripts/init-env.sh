#!/bin/sh
set -eu

if [ -e .env ]; then
  echo '.env ya existe; no se modificó.'
  exit 0
fi

umask 077
secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
cat > .env <<EOF
DJANGO_SECRET_KEY=$secret
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=biblioteca.dns.army,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://biblioteca.dns.army
MAX_PDF_MB=1024
EOF
echo 'Se creó .env con una clave secreta nueva.'
