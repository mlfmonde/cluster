FROM consul:0.8.5

ARG BUTTERVOLUME=1.2

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
    && pip install docker-compose==1.11.2 \
    && pip3 install pyyaml==3.12 \
    && pip3 install urllib3==1.21.1 \
    && git clone http://github.com/anybox/buttervolume \
    && cd buttervolume \
    && git checkout $BUTTERVOLUME \
    && python3 setup.py install \
    && cd /bin \
    && curl -o consul-template.zip https://releases.hashicorp.com/consul-template/0.19.0/consul-template_0.19.0_linux_amd64.zip \
    && unzip consul-template.zip \
    && rm consul-template.zip \
    && mkdir /consul/template \
    && sed -i 's/#AuthorizedKeysCommand .*/AuthorizedKeysCommand \/sbin\/authorizedkeys.py/' /etc/ssh/sshd_config \
    && sed -i 's/#AuthorizedKeysCommandUser .*/AuthorizedKeysCommandUser gw/' /etc/ssh/sshd_config

USER consul
COPY ssh /home/consul/.ssh
USER root
RUN chown -R consul: /home/consul \
    && chmod go-rwx /home/consul/.ssh/id_rsa \
    && mkdir -p /run/docker/plugins/ \
    && chmod g+rx /run/docker/plugins/ \
    && adduser consul root \
    && adduser -D -s /bin/false gw \
    && adduser gw docker

COPY authorizedkeys.py /sbin/
COPY handler.py /
COPY docker-entrypoint.sh /
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["agent", "-server", "-retry-join=10.91.210.57", "-retry-join=10.91.210.58", "-retry-join=10.91.210.59", "-bootstrap-expect=3", "-ui"]
