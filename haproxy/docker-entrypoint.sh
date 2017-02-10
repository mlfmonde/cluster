#!/bin/sh
set -e


# regenerate bundles at startup
PEMS=/etc/ssl/letsencrypt
BUNDLES=/etc/ssl/bundles
rm -rf $BUNDLES
mkdir -p $BUNDLES
for site in $(ls $PEMS); do
  if [ -e $PEMS/$site/$site.crt ] && [ -e $PEMS/$site/$site.key ]; then
    cat $PEMS/$site/$site.crt $PEMS/$site/$site.key > $BUNDLES/$site.pem
  fi
done

# first arg is `-f` or `--some-option`
if [ "${1#-}" != "$1" ]; then
	set -- haproxy "$@"
fi

if [ "$1" = 'haproxy' ]; then
	# if the user wants "haproxy", let's use "haproxy-systemd-wrapper" instead so we can have proper reloadability implemented by upstream
	shift # "haproxy"
	set -- "$(which haproxy-systemd-wrapper)" -p /run/haproxy.pid "$@"
fi

exec "$@"
