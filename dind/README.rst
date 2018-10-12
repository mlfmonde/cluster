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


TODO
----

* travis: resolve node1 consul to buttervolume connection: Failed to connect to Buttervolume
* travis: .travis.yml: reactive all commented install/before_script/script entries (commented for faster travis deploy during travis dev)
* run all tests, actually ci/run_tests.bash runs only test_new_service.py during dev process
