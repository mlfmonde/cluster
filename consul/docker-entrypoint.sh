#!/bin/sh
/usr/sbin/sshd -e

chown consul: /deploy

caddytemplate="/consul/template/caddy/Caddyfile.ctmpl:/consul/template/caddy/Caddyfile:/reload_caddy.sh"
haproxytemplate="/consul/template/haproxy/haproxy.cfg.ctmpl:/consul/template/haproxy/haproxy.cfg:/reload_haproxy.sh"

/bin/consul-template -once -template=$caddytemplate -template=$haproxytemplate &
/bin/consul-template       -template=$caddytemplate -template=$haproxytemplate &

# adapt the docker group of the container to the outside
DOCKER_GID=$(stat -c %g /run/docker.sock)
delgroup docker
addgroup -g $DOCKER_GID docker
adduser -S -u $DOCKER_GID -G $DOCKER_GID docker
adduser consul docker
adduser gw docker
PLUGINS=/run/docker/plugins
if [ -e $PLUGINS ]; then
    chmod g+rx $PLUGINS
    chgrp -R docker $PLUGINS
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
