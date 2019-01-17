FROM consul:1.4.0

ARG BUTTERVOLUME=3.4
ARG CONSULTEMPLATE=0.19.5
ARG DOCKERCOMPOSE=1.23.2

RUN apk add --no-cache \
      bash \
      docker \
      openssh-client \
      git \
      python3 \
    && pip3 install --upgrade pip fluent-logger \
    && pip install docker-compose==${DOCKERCOMPOSE} \
    && git clone https://github.com/anybox/buttervolume \
    && cd buttervolume \
    && git checkout $BUTTERVOLUME \
    && python3 setup.py install \
    && cd /bin \
    && curl -o consul-template.zip https://releases.hashicorp.com/consul-template/${CONSULTEMPLATE}/consul-template_${CONSULTEMPLATE}_linux_amd64.zip \
    && unzip consul-template.zip \
    && rm consul-template.zip \
    && mkdir /consul/template

USER consul
USER root
COPY . /
RUN python3 setup.py develop \
    && chown -R consul: /home/consul \
    && mkdir -p /run/docker/plugins/ \
    && chmod g+rx /run/docker/plugins/ \
    && adduser consul root \
    && adduser -D -s /bin/bash gw \
    && passwd -d gw \
    && sed -i 's/.*su-exec consul:consul .*/    set -- su-exec consul:docker "$@"/' /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["agent", "-dev", "-ui"]
