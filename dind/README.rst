Small private cluster
=====================

Docker in Docker
****************

For devs and CI, this Docker in docker (dind) setup is targetted for sandboxes and CI.
It aims to replace cluster_lab with Salt envs.

* one dind instance represents 1 node, where this repo 'cluster' is installed on each node
* 1 sandbox/CI cluster is a total of 4 nodes (4 dind instances) plus a ci container to run units tests


Bootstrap
---------

bootstrap flow::

    $ cd dind
    $ bash bootstrap.bash

* prepare btrfs images (4 images for 4 nodes)
* mount btrfs volumes of 4 nodes
* build dind docker image (dind env holds 1 node)
* up compose nodes (dind) and ci container
* in each node up services


Run tests
---------

run tests::

    $ (cd dind)
    $ bash ci/run_tests.bash

.. note::

    This command won't launch test that require push access to
    [mlfmonde/cluster_lab_test_service repo](https://github.com/mlfmonde/cluster_lab_test_service)
    located in ``ci/tests/auth_required`` to do so you may run the following
    command::

        docker-compose exec ci sh
        export GITHUB_API_TOKEN="petrus-v:YOUR_GITHUB_API_TOKEN" && \
            run-contexts /tests/auth_required/ -s -v


Start
-----

start an already bootstraped cluster::

    $ (cd dind)
    $ bash start.bash

* mount btrfs volumes of 4 nodes
* start each nodes and ci container
* for each nodes start services


Stop
----

stop a running cluster::

    $ (cd dind)
    $ bash stop.bash

* for each nodes stop services
* stop each nodes and ci container
* unmount btrfs volumes of 4 nodes

Clean Up
--------

Remove volumes and containers btrfs images... to leave env as we found it::

    $ (cd dind)
    $ bash cleanup.bash

* remove nodes and attached volumes
* unmount btrfs volumes
* remove btrfs images disk

TODO
----

* cache consul build in the local docker registry to avoid doing it on each nodes
* allow running auth required test using dev ssh keys
