doctest for the handler
=======================

handler.py is an event handler for consul watch.
See: https://www.consul.io/docs/agent/watches.html
Events are transmitted from one member to all other cluster members,
and each node handler should manage it accordingly.
It receives json through stdin, as a list of events.

Test
****

Run this doctest with::

    $ python3 test.py

Using from the shell
********************

From Consul (the expected way), just configure a watcher (see the docker-compose.yml of the consul MLF docker).

For instance inside a consul container with python3 installed::

    $ echo [{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}] | python3 handler.py

The same **test mode** ::

    $ echo [{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}] | python3 handler.py test

The test mode just prints the commands that should be executed.

Using as a Python library
*************************

This example does nothing because the "plop" event does not exist::

    >>> from handler import handle
    >>> events = '[{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}]'
    >>> handle(events, 'nowhere')

As a Python library in **test mode**, which we use for the doctests.

First try to deploy a master, pretending we are 'nepri'::

    >>> from base64 import b64encode
    >>> payload = "nepri ssh://git@git.mlfmonde.org:2222/hebergement/lycee-test-mlf"
    >>> payload = b64encode(payload.encode()).decode()
    >>> events = '[{"ID":"0","Name": "deploymaster","Payload": "%s","Version":1,"LTime":1}]' % payload
    >>> handle(events, 'nepri', test=True)
    rm -rf "/deploy/lycee-test-mlf"
    cd "/deploy" && git clone "ssh://git@git.mlfmonde.org:2222/hebergement/lycee-test-mlf"
    cd "/deploy/lycee-test-mlf" && docker-compose up -d
    cd "/deploy/lycee-test-mlf" && docker-compose config --services
    docker-compose ps -q 
    buttervolume snapshot 
    buttervolume schedule snapshot 60 
    POST http://localhost:8500/v1/agent/register/service {}
    rm -rf "/deploy/lycee-test-mlf"

The register_service expects a consul definition file to be present in the
repository of the service::

    >>> import tempfile, handler, requests
    >>> from os.path import join
    >>> import os, json
    >>> requests.post = print
    >>> handler.DEPLOY = tempfile.mkdtemp()
    >>> service = join(handler.DEPLOY, 'plop.com')
    >>> os.makedirs(service)
    >>> with open(join(service, 'service.json'), 'w') as f:
    ...     _ = f.write(json.dumps({'Name': 'plop'}))
    >>> _ = handler.Repository('nepri', 'http://truc/plop.com.git').register_consul()
    http://localhost:8500/v1/agent/register/service {"Name": "plop"}

Same with an invalid service::

    >>> _ = handler.Repository('nepri', 'http://truc/invalid.com.git').register_consul()
    Traceback (most recent call last):
    ...
    FileNotFoundError...

At the same time, the same deployment is run on tayt, it does nothing::

    >>> handle(events, 'tayt', test=True)
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


