FROM consul:1.0.6

ARG BUTTERVOLUME=2

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
    && pip install docker-compose==1.17.1 \
    && pip3 install pyyaml==3.12 \
    && pip3 install urllib3==1.21.1 \
    && git clone https://github.com/anybox/buttervolume \
    && cd buttervolume \
    && git checkout $BUTTERVOLUME \
    && python3 setup.py install \
    && cd /bin \
    && curl -o consul-template.zip https://releases.hashicorp.com/consul-template/0.19.4/consul-template_0.19.4_linux_amd64.zip \
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
    && passwd -d gw

COPY authorizedkeys.py /sbin/
COPY handler.py /
COPY reload_caddy.sh /
COPY reload_haproxy.sh /
COPY docker-entrypoint.sh /
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["agent", "-dev", "-ui"]
