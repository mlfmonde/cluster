#!/bin/sh

/bin/consul-template \
    -template="/consul/template/caddy/Caddyfile.ctmpl:/consul/template/caddy/Caddyfile" \
    -template="/consul/template/caddy/haproxy.cfg.ctmpl:/consul/template/haproxy/haproxy.cfg" &

exec /usr/local/bin/docker-entrypoint.sh "$@"
