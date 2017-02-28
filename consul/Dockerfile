FROM consul
RUN apk add --no-cache \
      docker \
      git \
      jq \
      openssh-client \
      py-pip \
      python3 \
    && pip install --upgrade pip \
    && pip install docker-compose \
    && git clone http://github.com/anybox/buttervolume \
    && cd buttervolume \
    && python3 setup.py install \
    && mkdir /deploy \
    && chown consul: /deploy

USER consul
COPY ssh /home/consul/.ssh
USER root
RUN chown -R consul: /home/consul \
    && delgroup docker \
    && addgroup -g 233 docker \
    && mkdir -p /run/docker/plugins/ \
    && adduser -S -u 233 -G docker docker \
    && adduser consul root \
    && adduser consul docker

COPY handler.py /
CMD ["agent", "-server", "-retry-join=10.91.210.57", "-bootstrap-expect=3"]
