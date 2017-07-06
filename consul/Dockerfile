FROM consul:0.8.5
RUN apk add --no-cache \
      docker \
      git \
      jq \
      openssh-client \
      py-pip \
      python3 \
    && pip install --upgrade pip \
    && pip install docker-compose \
    && pip3 install pyyaml \
    && git clone http://github.com/anybox/buttervolume \
    && cd buttervolume \
    && python3 setup.py install \
    && cd /bin \
    && curl -o consul-template.zip https://releases.hashicorp.com/consul-template/0.19.0/consul-template_0.19.0_linux_amd64.zip \
    && unzip consul-template.zip \
    && rm consul-template.zip \
    && mkdir /consul/template

USER consul
COPY ssh /home/consul/.ssh
USER root
RUN chown -R consul: /home/consul \
    && chmod go-rwx /home/consul/.ssh/id_rsa \
    && mkdir -p /run/docker/plugins/ \
    && chmod g+rx /run/docker/plugins/ \
    && adduser consul root

COPY handler.py /
COPY docker-entrypoint.sh /
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["agent", "-server", "-retry-join=10.91.210.57", "-retry-join=10.91.210.58", "-retry-join=10.91.210.59", "-bootstrap-expect=3", "-ui"]
