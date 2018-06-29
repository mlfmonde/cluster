Change log
==========

* Remove sshd support through consul. Was too limited and not working also
  becomes useless with the ``HAPROXY`` configuration.

* Add support to non migrable volumes

* Add support to ``CONSUL_CHECK_URLS`` to add extra consul checks

* Allow ``HAPROXY`` environment to add backends in ``http-in`` and ``https-in``
  frontend

* Add ``HAPROXY`` environment variable to manage haproxy.cfg from service
  definition (docker-compose.yml)

* Allow to bind relative path in docker-compose service, you will needs
  to move ``~/deploy`` directory to ``/deploy`` in order to make consistency
  tree between consul docker container and the host server. (cf `issue 10
  <https://github.com/mlfmonde/cluster/issues/10>`_)
