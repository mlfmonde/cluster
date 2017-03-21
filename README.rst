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

Consul web UI
-------------

The consul web UI runs on http://127.0.0.1:8500 on the host, through the consul docker running in host network_driver mode.
To access it from outside, create a ssh tunnel::

    $ ssh -L 8500:localhost:8500 nepri
    $ firefox localhost:8500

Deploy a new app
----------------

connect on any node, then run this from the cluster/ directory::

    docker-compose exec consul consul event -name=deploymaster "<targetnode> <repository_url>"

Example:

Deploy lycee-test-mlf on nepri::

    docker-compose exec consul consul event -name=deploymaster "nepri ssh://git@git.mlfmonde.org:2222/hebergement/lycee-test-mlf"

Switch an app on another node
-----------------------------

connect on any node, then run this from the cluster/ directory::

    docker-compose exec consul consul event -name=deploymaster "<targetnode> <repository_url>"

Example:

Deploy lycee-test-mlf on nepri::

    docker-compose exec consul consul event -name=deploymaster "nepri ssh://git@git.mlfmonde.org:2222/hebergement/lycee-test-mlf"

