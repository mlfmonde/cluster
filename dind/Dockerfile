FROM docker:stable-dind
LABEL maintainer "Vincent GREINER <vgreiner@anybox.fr>"

USER root

RUN apk update && apk add btrfs-progs
RUN mkdir -p /var/lib/buttervolume && mkdir /cluster

# consul port
EXPOSE 3500
