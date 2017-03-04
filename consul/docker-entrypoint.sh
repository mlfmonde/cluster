#!/bin/sh

chown consul: /deploy

/bin/consul-template \
    -template="/consul/template/caddy/Caddyfile.ctmpl:/consul/template/caddy/Caddyfile:docker restart cluster_caddy_1" \
    -template="/consul/template/haproxy/haproxy.cfg.ctmpl:/consul/template/haproxy/haproxy.cfg:docker restart cluster_haproxy_1" &

exec /usr/local/bin/docker-entrypoint.sh "$@"
