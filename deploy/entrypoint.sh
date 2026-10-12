#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    python manage.py migrate --noinput
    python manage.py createcachetable
fi

exec "$@"
