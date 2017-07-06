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

Restart
-------
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

    $ ssh -L 8500:localhost:8500 mlf@nepri.mlfmonde.org
    $ firefox localhost:8500

Deploy or move a new app
------------------------

connect on any node, then run this from the cluster/ directory::

    docker-compose exec consul consul event -name=deploymaster "<masternode> <slavenode> <repository_url>"

Example: deploy lycee-test-mlf on nepri and replicate on edjo::

    docker-compose exec consul consul event -name=deploymaster "nepri edjo ssh://git@git.mlfmonde.org:2222/hebergement/lycee-test-mlf"

Local development environment
-----------------------------

All docker containers can be use partially (not with ssl website) on developer
host.

.. note::

    You can use self signed certificate adding ``TLS: self_signed`` in the
    docker-compose service as environment variable.

You need to edit ``docker-compose.dev.yml``:

* Set environment variable CONSUL_BIND_INTERFACE to define
  your local interface connected to your router/internet.

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

    $ docker-compose exec consul consul event -name=deploymaster "localhost.localdomain ssh://git@git.mlfmonde.org:2222/hebergement/primaire.lyceemolieresaragosse.org.git"

Possibly replace localhost.localdomain with the hostname of your development machine.

Troubleshooting
***************

Caddyfile is not regenerated
----------------------------

Probably an error in the consul-template ``caddy/conf/Caddyfile.ctmpl`` or ``haproxy/conf/haproxy.cmtpl``,
or an invalid value in the KV store of Consul.

Try to regenerate the Caddyfile or haproxy.cfg manually to detect the error::

    $ ssh nepri  # or edjo or tayt
    $ cd cluster
    $ docker-compose exec --user consul consul sh
    $ cat /docker-entrypoint.sh
    $ /bin/consul-template -once -template="/consul/template/caddy/Caddyfile.ctmpl:/consul/template/caddy/Caddyfile:docker restart cluster_caddy_1"
    Consul Template returned errors:
    /consul/template/caddy/Caddyfile.ctmpl: execute: template: :17:57: executing "" at <parseJSON>: error calling parseJSON: unexpected end of JSON input

Also try to open the web ui to quickly check the deployed parameters::

    $ ssh -L 8500:localhost:8500 mlf@nepri
    $ firefox localhost:8500
    - click on Key/Value → Site
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
