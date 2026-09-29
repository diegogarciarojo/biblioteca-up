#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

python manage.py migrate --noinput
exec gunicorn biblioteca.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --threads 4 \
  --timeout 600 \
  --access-logfile - \
  --access-logformat '%(h)s %(l)s %(u)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s' \
  --error-logfile -
