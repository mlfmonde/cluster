# cluster ci
FROM python:3.5-alpine
LABEL maintainer "Vincent GREINER <vgreiner@anybox.fr>"

USER root

RUN apk update && apk add curl git openssh-client

COPY file/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

CMD ["/bin/sh"]
