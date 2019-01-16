FROM haproxy:1.8.17

# deploy default haproxy.cfg to ensure initial up
COPY ./conf/haproxy.default.cfg /usr/local/etc/haproxy/haproxy.cfg
# deploy haproxy template file
COPY ./conf/haproxy.cfg.ctmpl /usr/local/etc/haproxy/
