Cluster management
==================

Basic actions
*************

Start
-----

First start the btrfs volume plugin for docker separately::

    $ pushd buttervolume
    $ docker-compose up -d

Then start caddy, haproxy and consul::

    $ popd
    $ docker-compose up -d


Rebuild and restart
-------------------
::
    $ docker-compose up -d --build


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

    $ ssh -L 8500:localhost:8500 user@node1.example.com
    $ firefox localhost:8500


Deploy or move an app
---------------------

connect on any node, then run this from the cluster/ directory::

    docker-compose exec consul consul event -name=deploy '{"master": "<master_node>", "slave": "<slave_node>", "branch": "<branch_name>", "repo": "<repository_url>"}'

Example: deploy foobar on node1 and replicate on node2::

    docker-compose exec consul consul event -name=deploy '{"master": "node1", "slave": "node2", "branch": "master", "repo": "ssh://git@gitlab.example.com/hosting/foobar"}


Local development environment
-----------------------------

All docker containers can be used partially (not with ssl website) on the
developer host.

.. note::

    You can use a self signed certificate by adding ``tls self_signed`` in the
    CADDYFILE environment variable in the docker-compose service.

You need to edit ``docker-compose.dev.yml`` and set the CONSUL_BIND_INTERFACE
environment variable to define your local interface connected to your
router/internet.

Make sure the docker group has access to:

* ``/run/docker/plugins/`` directory with read/execution (``r-x``)
* ``/run/docker/plugins/btrfs.sock`` file with read/write (``rw-``)

Then::

    $ pushd buttervolume
    $ docker-compose up -d
    $ popd
    $ mkdir deploy
    $ docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

And you may have buttervolumeplugin/consul/caddy/haproxy on your personal host !

To deploy a website::

    $ docker-compose exec consul consul event -name=deploy '{"target": "localhost.localdomain", "branch": "master", "repo": "https://gitlab.example.com/hosting/foobar"}'

Possibly replace localhost.localdomain with the hostname of your development machine.

Troubleshooting
***************

Caddyfile is wrong
------------------

Probably an error in the Caddyfile stored in the consul KV store.

Try to regenerate the Caddyfile or haproxy.cfg manually to detect the error::

    $ ssh node1 -p 4022
    $ cd cluster
    $ docker-compose exec --user consul consul sh
    $ cat /docker-entrypoint.sh
    $ /bin/consul-template -once -template="/consul/template/caddy/Caddyfile.ctmpl:/consul/template/caddy/Caddyfile:docker restart cluster_caddy_1"

Also try to open the web ui to quickly check the deployed parameters::

    $ ssh -L 8500:localhost:8500 user@node1
    $ firefox localhost:8500
    - click on Key/Value → app
    - You can change values, it should trigger the recompute of the Caddyfile and haproxy.cfg if something changed in the resulting file.


proxy protocol
--------------

[Proxy protocol](https://www.haproxy.org/download/1.8/doc/proxy-protocol.txt)
let send real client IP from the first packet header even it's an encrypted
connection (like https).

.. warning::

    When setting ``send-proxy`` on haproxy configuration, the backend (the
    Caddy server) **have to** understand and accept the proxy protocole.
    (note: but in Caddy conf file once configured to listen proxy protole
    that works even it recived proper http / https)
