doctest for the handler
=======================

handler.py is an event handler for consul watch.
See: https://www.consul.io/docs/agent/watches.html
Events are transmitted from one member to all other cluster members,
and each node handler should manage it accordingly.
It receives json through stdin, as a list of events.

Test
****

WARNING: this is an intrusive test that depends on some containers running.
Before the test you should make sure you run on BTRFS filesystem, then::

    $ sudo -s
    # docker network create cluster_default
    # cd ../buttervolume
    # docker-compose up -d

Run this doctest with::

    $ sudo -E python3 test.py

(-E is to keep the environment so that pulling from the gitlab works like with your normal user)

Using from the shell
********************

From Consul (the expected way), just configure a watcher (see the docker-compose.yml of the consul MLF docker).

For instance, from inside a consul container with python3 installed::

    $ echo [{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}] | python3 handler.py

The same in **test mode** ::

    $ echo [{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}] | python3 handler.py test

The test mode just prints the commands that should be executed.

Passing data as argument
************************

Another useful mode is available to manually test a deployment, just pass the data as first argument to the handler::

    $ python3 handler.py '[{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}]'

This way, it is easier to put a **pdb** debugger in the handler.

Using as a Python library
*************************

This example does nothing because the "plop" event does not exist::

    >>> import handler
    >>> events = '[{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}]'
    >>> handler.handle(events, 'nowhere')

As a Python library in **test mode**, which we use for the doctests.

First try to deploy a master, pretending we are 'nepri'::

    >>> import tempfile
    >>> handler.DEPLOY = tempfile.mkdtemp()
    >>> from base64 import b64encode
    >>> payload = "nepri ssh://git@git.mlfmonde.org:2222/hebergement/lycee-test-mlf"
    >>> payload = b64encode(payload.encode()).decode()
    >>> events = '[{"ID":"0","Name": "deploy","Payload": "%s","Version":1,"LTime":1}]' % payload
    >>> handler.handle(events, 'nepri', test=True)
    buttervolume snapshot lyceetestmlf_dbdata
    buttervolume schedule snapshot 60 lyceetestmlf_dbdata
    buttervolume snapshot lyceetestmlf_wwwdata
    buttervolume schedule snapshot 60 lyceetestmlf_wwwdata
    consul kv put site/lyceetestmlf.anybox.eu {"ct": "lyceetestmlf_wordpress_1", "url": "lyceetestmlf.anybox.eu", "node": "nepri"}
    POST http://localhost:8500/v1/agent/service/register {
        "Name": "lyceetestmlf.anybox.eu",
        "Check": {
            "HTTP": "https://lyceetestmlf.anybox.eu/",
            "Interval": "30s"
        }
    }

Same with an invalid service::

    >>> _ = handler.Application('http://truc/invalid.com.git').register_consul()
    Traceback (most recent call last):
    ...
    FileNotFoundError...

At the same time, the same deployment is run on tayt, it does nothing::

    >>> handler.handle(events, 'tayt', test=True)
    No action

Then we deploy a slave on edjo::

    >>>

The slave already pulled a first snapshot from the master::

    >>>

Next snapshot pulls are already scheduled::

    >>>

We can redeploy a new version the same way. docker-compose is responsible to recreate the image.
We notice the current version is first stored in consul::

    >>>

If something goes wrong with the new version, we can downgrade to the latest
stable revision, by relaunching the deployment with a specified revision::

    >>> 


future TODO ?
Now we want to upgrade the app currently on nepri with a new image, and run a
potential complex upgrade procedure. We just send an upgrade event to the cluster with
a choice of the upgrading slave.  Then the master should stop, (todo put a
maintenance page) trigger a snapshot and send it to the slaves, and at the same
time the upgrading slave waits for the incoming snapshot. Once received, the
slave snapshots it as a volume, deploys the new image, run the potential
upgrade procedure, and register it in consul.

Now we want to switch the master to another machine. We just promote the specified slave::

    >>>


