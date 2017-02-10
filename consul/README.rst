doctest for the handler
=======================

handler.py is an event handler for consul watch.
See: https://www.consul.io/docs/agent/watches.html
It receives json through stdin, as a list of events.

Usage
-----

From Consul (the expected way), just configure a watcher (see the docker-compose.yml of the consul MLF docker)

From the shell::

    $ echo [{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}] | python3 handler.py

From the shell in **test mode** ::

    $ echo [{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}] | python3 handler.py test

As a Python library::

This example does nothing because the "plop" event does not exist::

    >>> from handler import handle
    >>> events = '[{"ID":"0","Name":"plop","Payload":"cGxvcDI=","Version":1,"LTime":1}]'
    >>> handle(events, 'nowhere')

As a Python library in **test mode**, which we use for the doctests.

First try with a deploy, pretending we are 'nepri'::

    >>> from base64 import b64encode
    >>> payload = "nepri git.mlfmonde.org/plop/plop"
    >>> payload = b64encode(payload.encode()).decode()
    >>> events = '[{"ID":"0","Name": "deploymaster","Payload": "%s","Version":1,"LTime":1}]' % payload
    >>> handle(events, 'nepri', test=True)
    cd /tmp
    && git clone git.mlfmonde.org/plop/plop

Same deploy on tayt::

    >>> handle(events, 'tayt', test=True)
    No action
