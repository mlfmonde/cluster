FROM alpine:3.5
LABEL maintainer "Pierre Verkest <pverkeset@anybox.fr>"
# This is a copy from the official dockerfile to manage plugins we needs
# the default image contains http.git wich we don't use but not
# http.proxyprotocol required (by #8847)
# copy from https://github.com/abiosoft/caddy-docker/blob/master/Dockerfile

LABEL caddy_version="0.10.7" architecture="amd64"

ARG plugins=http.proxyprotocol

RUN apk add --no-cache openssh-client tar curl

RUN curl --silent --show-error --fail --location \
      --header "Accept: application/tar+gzip, application/x-gzip, application/octet-stream" -o - \
      "https://caddyserver.com/download/linux/amd64?plugins=${plugins}" \
    | tar --no-same-owner -C /usr/bin/ -xz caddy \
 && chmod 0755 /usr/bin/caddy \
 && /usr/bin/caddy -version

EXPOSE 80 443 2015
VOLUME /root/.caddy
WORKDIR /srv

COPY conf/ /etc/caddy/
COPY index /srv/

ENTRYPOINT ["/usr/bin/caddy"]
CMD ["--conf", "/etc/caddy/Caddyfile", "--log", "stdout"]
