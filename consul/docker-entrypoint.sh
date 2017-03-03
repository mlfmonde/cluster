#!/bin/sh

chown consul: /deploy

/bin/consul-template \
    -template="/consul/template/caddy/Caddyfile.ctmpl:/consul/template/caddy/Caddyfile:docker kill -s USR1 caddy_server_1" \
    -template="/consul/template/haproxy/haproxy.cfg.ctmpl:/consul/template/haproxy/haproxy.cfg:docker kill -s HUP haproxy_server_1" &

exec /usr/local/bin/docker-entrypoint.sh "$@"
