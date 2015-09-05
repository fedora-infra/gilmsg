""" gilmsg - A reliability layer on top of fedmsg.

See the README for documentation.
https://github.com/fedora-infra/gilmsg/

Author:  Ralph Bean <rbean@redhat.com>
License: LGPLv2+

"""


import threading
import time

import logging
log = logging.getLogger("fedmsg")
logging.basicConfig()

import fedmsg
import fedmsg.commands.logger
import fedmsg.consumers
import fedmsg.crypto


import pkg_resources
gilmsg_version = pkg_resources.get_distribution('gilmsg').version

__all__ = ['init', 'publish', 'tail_messages', 'Timeout']

# Passthrough.  Just here for API compat.
init = fedmsg.init


class Timeout(Exception):
    pass


class AckListener(threading.Thread):
    c = None
    msg_id = None
    expectations = None
    results = []
    time_is_up = False


    def set_config(self, config):
        self.c = config

    def set_msg_id(self, msg_id):
        self.msg_id = msg_id

    def set_expectations(self, expectations):
        self.expectations = expectations

    def sanity_check(self):
        if not self.msg_id:
            raise ValueError("thread starting before msg_id was set")
        if not self.expectations:
            raise ValueError("thread starting before expectations was set")
        if not self.c:
            raise ValueError("thread starting before config was set")

    def die(self):
        self.time_is_up = True

    def run(self):
        self.sanity_check()
        ack_topic = '.'.join([
            self.c['topic_prefix'],
            self.c['environment'],
            'gilmsg.ack',
        ])

        # Go into a loop, receiving gilmsg ACK messages from the fedmsg bus
        for n, e, t, msg in fedmsg.tail_messages(**self.c):

            # Did we run out of time?
            if self.time_is_up:
                return

            # Throw away anything that's not an ACK produced by a consumer.
            if t != ack_topic:
                continue

            # We should only know about ACKs.  Is this an ACK for *ours*?
            if not msg['msg']['ack_msg_id'] == self.msg_id:
                continue

            # We can declare that multiple other systems *must* receive our
            # message.  Write down who is acking this one.
            for signer in self.expectations:
                if not fedmsg.crypto.validate_signed_by(msg, signer, **self.c):
                    continue
                self.results.append(signer)

            # Check to see if we collected all the pokemon.
            # If all the people that we wanted to get the message have sent
            # us ACKs for this message_id, then hooray!  If not, go back into
            # tail_messages to wait for more ACKs.  The clock is ticking....
            if set(self.results) == set(self.expectations):
                return


def publish(topic=None, msg=None, modname=None,
            recipients=None,
            ack_timeout=0.25,
            **kw):
    if not recipients:
        log.warn("Why use gilmsg if no recipients are specified?  "
                 "Just use fedmsg instead.")
        return fedmsg.publish(topic=topic, msg=msg, modname=modname, **kw)

    listener = AckListener()
    listener.set_config(kw)
    listener.set_expectations(recipients)

    def pre_fire_hook(msg):
        msg['gilmsg_version'] = gilmsg_version
        listener.set_msg_id(msg['msg_id'])
        listener.start()
        # Give the listener a good head start...
        time.sleep(kw['post_init_sleep'] * 2)

    fedmsg.publish(
        topic=topic,
        msg=msg,
        modname=modname,
        pre_fire_hook=pre_fire_hook,
        **kw
    )

    listener.join(timeout=ack_timeout)
    if listener.isAlive():
        listener.die()
        # Then the timeout expired and we haven't received our ACKs yet.
        raise Timeout("Received %i acks from %i of %i systems in %d seconds" % (
            len(listener.results),
            len(set(listener.results)),
            len(set(recipients)),
            ack_timeout,
        ))
    else:
        # Hopefully everything went well?
        assert len(set(listener.results)) == len(set(recipients)), listener.results


def _acknowledge(message, **config):
    if 'gilmsg_version' not in message:
        return
    ack = dict(ack_msg_id=message['msg_id'])
    fedmsg.publish(topic="ack", msg=ack, **config)


def tail_messages(topic="", passive=False, **kw):
    for n, e, t, m in fedmsg.tail_messages(topic=topic, passive=passive, **kw):
        # Only acknowledge gilmsg messages to avoid catastrophic spam storm
        _acknowledge(m, **kw)
        yield n, e, t, m


class GilmsgConsumer(fedmsg.consumers.FedmsgConsumer):
    """ Extend this to make your own robust consumers. """
    def pre_consume(self, m):
        super(GilmsgConsumer, self).pre_consume(m)
        _acknowledge(m, **self.hub.config)


class LoggerCommand(fedmsg.commands.logger.LoggerCommand):
    extra_args = fedmsg.commands.logger.LoggerCommand.extra_args + [
        (['--recipients'], {
            'dest': 'recipients',
            'metavar': 'SIGNER',
            'nargs': '+',
            'help': 'Names on the certificates of some required recipients',
        }),
        (['--ack-timeout'], {
            'dest': 'ack_timeout',
            'metavar': 'SECONDS',
            'default': 0.25,
            'type': float,
            'help': 'Number of seconds to wait for acknowledgement.',
        }),
    ]

    def _log_message(self, kw, message):
        if not self.config['recipients']:
            raise ValueError("'--recipients' is required.")

        if kw['json_input']:
            msg = fedmsg.encoding.loads(message)
        else:
            msg = {'log': message}

        # Use our publish function, not fedmsg's
        publish(
            msg=msg,
            **self.config)


def logger_cli():
    return LoggerCommand().execute()
