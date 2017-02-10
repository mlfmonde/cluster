FROM consul
RUN apk add --no-cache \
      git \
      openssh-client \
      python3 \
    && mkdir /root/.ssh \
    && echo -e "Host git.mlfmonde.org\n\tStrictHostKeyChecking no\n" >> ~/.ssh/config
COPY handler.py /
CMD ["agent", "-server", "-retry-join=10.91.210.57", "-bootstrap-expect=3"]
