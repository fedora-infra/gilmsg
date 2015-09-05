gilmsg
======

.. split here::

A reliability layer on top of fedmsg.

What is "Reliability"?
----------------------

Every few months, a discussion comes up about *fedmsg reliability*.
Typically, a team somewhere in the Fedora Project will be looking into how they
can streamline their workflows by either using data from or sending data to the
bus. We end up having a lengthy discussion in IRC until the matter gets settled.
But that conversation gets lost in the ether of freenode and the *next* time a
different team has the same questions we have to have the conversation over
again.

`fedmsg <http://fedmsg.com>`_ is a set of python tools (one part library, one
part framework) that we use around Fedora Infrastructure to enable system
processes to publish and listen for messages.  We typically call it our
"message bus", but that is bad nomenclature; it doesn't accurately describe
what is going on.  When a process wants to publish fedmsg messages, it invokes
``fedmsg.publish(...)`` which reads in some configuration from disk, binds a
socket to a port if it hasn't already, and writes the message there.  When
another process wants to consume fedmsg messages, it invokes
``fedmsg.tail_messages()`` (or registers itself with an already listening
``fedmsg-hub`` daemon) which then *connects* a socket to the bound port of the
other process to ``recv`` the message(s).

A little more detail now:  the call to ``fedmsg.publish`` doesn't manage the
socket binding and sending itself.  It hands things off to zeromq which in
turn hands things off to a number of worker threads it manages.  Zeromq keeps
an internal queue of messages it has been asked to send, which it sends as
fast as it can.  A key takeaway here is that it is "fire-and-forget": a web
application that has been enabled to publish fedmsg messages will ask the fedmsg
library to do so, and then walk away to finish its database transactions or do
whatever other work it is intended to do.  fedmsg (really zeromq here) opaquely
sends the message as soon as it has a spare moment.

(As an aside, the process involves even more than that.  Outgoing
messages are signed using cryptographic certificates.  Python data types are
serialized.  Incoming messages are validated and deserialized and checked
against an authorization policy about who is allowed to sign what messages,
etc..  We'll come back to this.)

Let's quote `the zguide <http://zguide.zeromq.org/php:chapter4>`_::

    Most people who speak of "reliability" don't really know what they mean. We
    can only define reliability in terms of failure. That is, if we can handle
    a certain set of well-defined and understood failures, then we are reliable
    with respect to those failures. No more, no less. So let's look at the
    possible causes of failure in a distributed ZeroMQ application

In practice, we do not "drop messages" in Fedora Infrastructure.  We have run a
number of experiments that demonstrate this to a degree sufficient
to establish confidence with a number of other teams.

In theory, though, there's a race condition here.  You could start your
publishing service and it could publish a message *before* anyone connects to
listen for it.  It would be lost.  Again, in practice we have appropriate
delays and reconnect intervals (with exponential backoff) configured to make
this a non-issue.

Still, there could be network partitions -- a listening service may suddenly
find itself walled off from a publishing service by dead routers or a
misconfigured firewall or a dead vpn or catastrophe, in all of such cases:
messages will be lost.

Designing Reliability
---------------------

The zguide provides a good description of `how to think about and approach
reliability for REQ-REP socket patterns
<http://zguide.zeromq.org/php:chapter4#Designing-Reliability>`_.  However,
we've settled over the last few years on using *only* the PUB-SUB socket
pattern for fedmsg.  Adding another pattern (REQ-REP) alongside that smells
wrong (it's currently so simple).

The approach here in `gilmsg <https://github.com/fedora-infra/gilmsg>`_ is to
layer a reliability check *on top of* the existing PUB-SUB fedmsg framework.

Here's how it works broadly:

- When ``gilmsg.publish(...)`` is invoked, you must declare a list of
  **required recipients**.
- A background thread is started that listens for **ACK** messages on the whole
  bus.
- If an **ACK** is not received from all ``recipients`` within a given timeout,
  then a ``Timeout`` exception is raised.

Failure cases this addresses:

- If an intended recipient is offline when the message is published, we'll
  raise an exception so that the originating process can fail and alert the
  operator.
- If an intended recipient is online, but we're suffering from a network
  partition, the publisher will fail loudly.

It is possible for us to have *False Negatives*:

- If the intended recipient is online, but cannot publish the *ACK* back due to
  a one-way network failure or a misconfiguration, the publisher will fail
  loudly *even though* the consumer did receive the message.

It is not possible for us to have *False Positives*.  If the producer completes
execution, we can be sure the consumer received the message.

Some Details
------------

- We are sure that the ACKs comes from the ``recipients`` we declared because
  the ACKs are *cryptographically signed*.
- We take care to distinguish between ACKs for *the message we published* and
  ACKs for *other messages we know nothing about*.
- We start the ACK-listening socket on the producer in a thread **before** we
  publish the original message.  This is necessary to avoid a race condition
  where we publish our original message but the ACK comes back before we get a
  chance to start listening for it.

Why not use gilmsg?
-------------------

fedmsg has worked very well.  We have a `long list of integrated message
producers in Fedora Infrastructure <https://fedora-fedmsg.readthedocs.org>`_.
The success is due in part to just how *dumb* fedmsg is.  It has contributed to
the rise of a *loosely coupled architecture*, which was the original aim.  When
some Fedora hacker gets an idea, then can hook onto the bus to consume messages
without having to negotiate with anyone about it.  They can produce messages
without having to go to committee.

As an example:  you can stand up Bodhi2 web app on your local box, and it will
"publish to fedmsg" without you having to start any additional services or
anything like that.  It will publish to fedmsg on your laptop, no one will
be listening, and it won't care.

In contrast, with gilmsg-enabled services:

- Your producers will declare their required consumers.
- As you add more consumers, you're going to have to patch your producers
  leading to an exponential number of code changes to get new things done.
- You cannot run or test a gilmsg-enabled service on your own box without a
  replica of the whole production environment, since it will *require* that
  other services respond to it.
- Your ensemble of production services becomes brittle -- prone to one dead
  service bringing the others down.

gilmsg-enabled services are *tightly coupled*.

----

A cosmetic note:

- The more gilmsg-enabled producer/consumer pairs you bring on line, the more
  spam you'll have on the bus.  It can handle the throughput(!) but it will
  make the datagrepper logs less readable as you add more.

Using gilmsg
------------

It is API backwards compatible with fedmsg core.  So, write your script to use
fedmsg first.  If at some point in the future you decide that you *must* have
the set of guarantees that gilmsg provides, then port to gilmsg.

**Publishing** with ``.publish(..)`` from Python::

    import gilmsg

    import fedmsg.config
    config = fedmsg.config.load_config()

    gilmsg.publish(
        topic="whatever",
        msg=dict(foo="bar"),
        recipients=(
            "bodhi-bodhi-backend01.phx2.fedoraproject.org",
            "shell-autocloud01.phx2.fedoraproject.org",
        ),
        ack_timeout=0.25,  # 0.25 seconds
        **config)

**Publishing** from the shell with ``gilmsg-logger`` with a timeout of 3 seconds::

   echo testing | gilmsg-logger --recipients shell-value01.phx2.fedoraproject.org --ack-timeout 3

Compare the above with `publishing with fedmsg alone
<http://www.fedmsg.com/en/latest/publishing/>`_.

----

**Consuming** with ``.tail_messages(..)`` in Python::

    import gilmsg

    import fedmsg.config
    config = fedmsg.config.load_config()

    target = "org.fedoraproject.prod.compose.rawhide.complete"
    for name, ep, t, msg in gilmsg.tail_messages(topic=target, **config):
        # The ACK has already been sent at this point.
        print "Received", t, msg['msg_id']

**Consuming** with the "Hub-Consumer" approach::

    import gilmsg

    class MyConsumer(gilmsg.GilmsgConsumer):
        topic = "org.fedoraproject.prod.compose.rawhide.complete"

        def consume(self, message):
            # The ACK has already been sent at this point.
            print "Received", message['topic'], message['msg_id']

Compare the above with `consuming with fedmsg alone
<http://www.fedmsg.com/en/latest/consuming/>`_.
