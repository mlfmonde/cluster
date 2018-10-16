# cluster node docker in docker (dind)
FROM docker:stable-dind
LABEL maintainer "Vincent GREINER <vgreiner@anybox.fr>"

USER root

RUN apk update && apk add btrfs-progs py-pip

# docker-compose: for alpine we install it via pip (KO if you follow docker-compose install documentation)
RUN pip install --upgrade pip && pip install docker-compose

# consul port
EXPOSE 8500
