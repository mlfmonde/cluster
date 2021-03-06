#!/bin/sh

chown -R consul: /deploy

caddytemplate="/consul/template/caddy/Caddyfile.ctmpl:/caddy/Caddyfile:/reload_caddy.sh"
haproxytemplate="/consul/template/haproxy/haproxy.cfg.ctmpl:/haproxy/haproxy.cfg:/reload_haproxy.sh"

/bin/consul-template -once -template=$caddytemplate -template=$haproxytemplate &
/bin/consul-template       -template=$caddytemplate -template=$haproxytemplate &

# adapt the docker group of the container to the outside
DOCKER_GID=$(stat -c %g /run/docker.sock)
delgroup $(getent group $DOCKER_GID | cut -d: -f1)
delgroup docker
addgroup -g $DOCKER_GID docker
adduser -S -u $DOCKER_GID -G docker docker
adduser consul docker
adduser gw docker
chown -R consul: /home/consul/.ssh
PLUGINS=/run/docker/plugins
if [ -e $PLUGINS ]; then
    chmod -R g+rx $PLUGINS
    chgrp -R docker $PLUGINS
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
