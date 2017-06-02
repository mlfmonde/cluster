FROM consul:0.7.5
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
    && curl -o consul-template.zip https://releases.hashicorp.com/consul-template/0.18.1/consul-template_0.18.1_linux_amd64.zip \
    && unzip consul-template.zip \
    && rm consul-template.zip \
    && mkdir /consul/template

USER consul
COPY ssh /home/consul/.ssh
USER root
RUN chown -R consul: /home/consul \
    && chmod go-rwx /home/consul/.ssh/id_rsa \
    && delgroup docker \
    && addgroup -g 233 docker \
    && mkdir -p /run/docker/plugins/ \
    && adduser -S -u 233 -G docker docker \
    && adduser consul root \
    && adduser consul docker

COPY handler.py /
COPY docker-entrypoint.sh /
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["agent", "-dev", "-ui"]
