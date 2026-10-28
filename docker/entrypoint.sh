#!/bin/sh
# Container entrypoint for MDT Portfolio.
#
# Without arguments (the normal case) it prepares the database and starts the app:
#   mdt db upgrade  ->  mdt seed  ->  exec mdt serve --host 0.0.0.0 --port 8080
# With arguments it runs them instead, as the unprivileged user, for example:
#   docker compose run --rm app mdt check
#
# Inside the container the server always listens on 0.0.0.0:8080. HOST and PORT
# in .env only choose where docker compose publishes that port on the host
# (default 127.0.0.1:8080, see docker-compose.yml). They never change the
# address inside the container.
#
# Privileges: the container starts as root only to make the data directory
# writable for the unprivileged user "app". On the first start the Docker daemon
# creates a missing ./data bind mount as root, which "app" could not write to.
# The script then re-executes itself as "app" (setpriv, from util-linux), so
# migrations, seeding and the server never run as root.
set -eu

APP_USER=app
DATA_DIR="${DATA_DIR:-/app/data}"

log() {
    printf '[entrypoint] %s\n' "$*" >&2
}

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    # Change only what is wrong, so later starts stay cheap. -xdev: do not
    # descend into other file systems mounted below DATA_DIR. chown -h: change
    # symlinks themselves, never their targets.
    if ! find "$DATA_DIR" -xdev \( ! -user "$APP_USER" -o ! -group "$APP_USER" \) \
        -exec chown -h "$APP_USER:$APP_USER" {} +; then
        log "warning: could not change the owner of every file in $DATA_DIR"
    fi
    exec setpriv --reuid="$APP_USER" --regid="$APP_USER" --init-groups --inh-caps=-all \
        env HOME="/home/$APP_USER" "$0" "$@"
fi

if [ ! -w "$DATA_DIR" ]; then
    log "error: $DATA_DIR is not writable for uid $(id -u), gid $(id -g)."
    log "Make ./data on the host writable for that user, for example:"
    log "  sudo chown -R $(id -u):$(id -g) data"
    exit 1
fi

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

log "applying database migrations (mdt db upgrade)"
mdt db upgrade

log "loading vocabularies and seed data, idempotent (mdt seed)"
mdt seed

log "starting the server on 0.0.0.0:8080 inside the container"
exec mdt serve --host 0.0.0.0 --port 8080
