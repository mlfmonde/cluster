doctest for the handler
=======================

handler.py is an event handler for consul watch.
See: https://www.consul.io/docs/agent/watches.html
Events are transmitted from one member to all other cluster members,
and each node handler should manage it accordingly.
It receives json through stdin, as a list of events.

Usage
*****

From the shell
--------------

From Consul (the expected way), just configure a watcher (see the docker-compose.yml of the consul MLF docker).

For instance inside a consul container with python3 installed::

    $ echo [{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}] | python3 handler.py

The same **test mode** ::

    $ echo [{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}] | python3 handler.py test

The test mode just prints the commands that should be executed.

As a Python library
-------------------

This example does nothing because the "plop" event does not exist::

    >>> from handler import handle
    >>> events = '[{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}]'
    >>> handle(events, 'nowhere')

As a Python library in **test mode**, which we use for the doctests.

First try with a deploy, pretending we are 'nepri'::

    >>> from base64 import b64encode
    >>> payload = "nepri ssh://git@git.mlfmonde.org:2222/hebergement/lycee-test-mlf"
    >>> payload = b64encode(payload.encode()).decode()
    >>> events = '[{"ID":"0","Name": "deploymaster","Payload": "%s","Version":1,"LTime":1}]' % payload
    >>> handle(events, 'nepri', test=True)
    cd "/deploy" && rm -rf "/deploy/lycee-test-mlf"
    cd "/deploy" && git clone ssh://git@git.mlfmonde.org:2222/hebergement/lycee-test-mlf
    cd "/deploy/lycee-test-mlf" && docker-compose up -d
    cd "/deploy" && rm -rf "/deploy/lycee-test-mlf"

Same deploy on tayt::

    >>> handle(events, 'tayt', test=True)
    No action
