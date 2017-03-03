#!/bin/sh

chown consul: /deploy

/bin/consul-template \
    -template="/consul/template/caddy/Caddyfile.ctmpl:/consul/template/caddy/Caddyfile" \
    -template="/consul/template/haproxy/haproxy.cfg.ctmpl:/consul/template/haproxy/haproxy.cfg" &

exec /usr/local/bin/docker-entrypoint.sh "$@"
