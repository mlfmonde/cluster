FROM consul
RUN apk add --no-cache \
      docker \
      git \
      jq \
      openssh-client \
      py-pip \
      python3 \
    && pip install --upgrade pip \
    && pip install docker-compose
USER consul
COPY ssh /home/consul/.ssh
COPY handler.py /
CMD ["agent", "-server", "-retry-join=10.91.210.57", "-bootstrap-expect=3"]
