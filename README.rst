Cluster management
==================

Start
-----

First start the btrfs volume plugin for docker separately::

    $ pushd buttervolume
    $ docker-compose up -d

Then start caddy, haproxy and consul::

    $ popd
    $ docker-compose up -d

Stop
----

Same in reverse order::

    $ docker-compose down
    $ cd buttervolume
    $ docker-compose down
