FROM consul
RUN apk add --no-cache python3
COPY handler.py /
CMD ["agent", "-server", "-retry-join=10.91.210.57", "-bootstrap-expect=3"]
