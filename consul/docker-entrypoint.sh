#!/bin/sh
/usr/sbin/sshd -e

chown consul: /deploy

/bin/consul-template \
    -template="/consul/template/caddy/Caddyfile.ctmpl:/consul/template/caddy/Caddyfile:docker restart cluster_caddy_1" \
    -template="/consul/template/haproxy/haproxy.cfg.ctmpl:/consul/template/haproxy/haproxy.cfg:docker restart cluster_haproxy_1" &

# adapt the docker group of the container to the outside
DOCKER_GID=$(stat -c %g /var/run/docker.sock)
delgroup docker
addgroup -g $DOCKER_GID docker
adduser -S -u $DOCKER_GID -G $DOCKER_GID docker
adduser consul docker

exec /usr/local/bin/docker-entrypoint.sh "$@"
