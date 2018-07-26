FROM consul:1.2.1

ARG BUTTERVOLUME=3.4
ARG CONSULTEMPLATE=0.19.4
ARG DOCKERCOMPOSE=1.20.1

RUN apk add --no-cache \
      bash \
      docker \
      git \
      jq \
      openrc \
      openssh-client \
      openssh-server \
      py-pip \
      python3 \
    && rc-status \
    && touch /run/openrc/softlevel \
    && rc-update add sshd \
    && /etc/init.d/sshd start \
    && pip install --upgrade pip \
    && pip install docker-compose==${DOCKERCOMPOSE} \
    && pip3 install pyyaml==3.12 \
    && pip3 install urllib3==1.22 \
    && pip3 install docker \
    && git clone https://github.com/anybox/buttervolume \
    && cd buttervolume \
    && git checkout $BUTTERVOLUME \
    && python3 setup.py install \
    && cd /bin \
    && curl -o consul-template.zip https://releases.hashicorp.com/consul-template/${CONSULTEMPLATE}/consul-template_${CONSULTEMPLATE}_linux_amd64.zip \
    && unzip consul-template.zip \
    && rm consul-template.zip \
    && mkdir /consul/template \
    && sed -i 's/#AuthorizedKeysCommand .*/AuthorizedKeysCommand \/sbin\/authorizedkeys.py/' /etc/ssh/sshd_config \
    && sed -i 's/#AuthorizedKeysCommandUser .*/AuthorizedKeysCommandUser gw/' /etc/ssh/sshd_config

USER consul
USER root
RUN chown -R consul: /home/consul \
    && mkdir -p /run/docker/plugins/ \
    && chmod g+rx /run/docker/plugins/ \
    && adduser consul root \
    && adduser -D -s /bin/bash gw \
    && passwd -d gw \
    && sed -i 's/.*su-exec consul:consul .*/    set -- su-exec consul:docker "$@"/' /usr/local/bin/docker-entrypoint.sh

COPY authorizedkeys.py /sbin/
COPY handler.py /
COPY reload_caddy.sh /
COPY reload_haproxy.sh /
COPY docker-entrypoint.sh /
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["agent", "-dev", "-ui"]
