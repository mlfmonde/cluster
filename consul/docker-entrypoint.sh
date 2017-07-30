#!/bin/sh
/usr/sbin/sshd -e

chown consul: /deploy

/bin/consul-template \
    -template="/consul/template/caddy/Caddyfile.ctmpl:/consul/template/caddy/Caddyfile:/reload_caddy.sh" \
    -template="/consul/template/haproxy/haproxy.cfg.ctmpl:/consul/template/haproxy/haproxy.cfg:/reload_haproxy.sh" &

# adapt the docker group of the container to the outside
DOCKER_GID=$(stat -c %g /var/run/docker.sock)
delgroup docker
addgroup -g $DOCKER_GID docker
adduser -S -u $DOCKER_GID -G $DOCKER_GID docker
adduser consul docker
adduser gw docker

exec /usr/local/bin/docker-entrypoint.sh "$@"
