#
# INTEL CONFIDENTIAL
#
# Copyright 2013 Intel Corporation All Rights Reserved.
#
# The source code contained or described herein and all documents related
# to the source code ("Material") are owned by Intel Corporation or its
# suppliers or licensors. Title to the Material remains with Intel Corporation
# or its suppliers and licensors. The Material contains trade secrets and
# proprietary and confidential information of Intel or its suppliers and
# licensors. The Material is protected by worldwide copyright and trade secret
# laws and treaty provisions. No part of the Material may be used, copied,
# reproduced, modified, published, uploaded, posted, transmitted, distributed,
# or disclosed in any way without Intel's prior express written permission.
#
# No license under any patent, copyright, trade secret or other intellectual
# property right is granted to or conferred upon you by disclosure or delivery
# of the Materials, either expressly, by implication, inducement, estoppel or
# otherwise. Any license under such intellectual property rights must be
# express and approved by Intel in writing.


from django.core.handlers.wsgi import WSGIHandler
from django.db import transaction
import gevent.wsgi

from chroma_core.models import ClientCertificate
from chroma_core.services.rpc import ServiceRpcInterface
from chroma_core.services.http_agent.host_state import HostStateCollection, HostStatePoller
from chroma_core.services.http_agent.queues import HostQueueCollection, AmqpRxForwarder, AmqpTxForwarder
from chroma_core.services.http_agent.sessions import SessionCollection
from chroma_core.services import ChromaService, ServiceThread, log_register
from chroma_agent_comms.views import MessageView

from settings import HTTP_AGENT_PORT


log = log_register(__name__)


class HttpAgentRpc(ServiceRpcInterface):
    methods = ['reset_session', 'remove_host', 'reset_plugin_sessions']


# TODO: interesting tests:
# * Run through some error-less scenarios and grep the logs for WARN and ERROR
# * Modify some client and server certificates slightly and check they are rejected (i.e.
#   check that we're really verifying the signatures and not just believing certificates)
# * remove a host and then try connecting with that host's old certificate
# * check that after adding and removing a host, no chroma-agent or chroma-agent-daemon services are running


class Service(ChromaService):
    def reset_session(self, fqdn, plugin, session_id):
        return self.sessions.reset_session(fqdn, plugin, session_id)

    def reset_plugin_sessions(self, plugin):
        return self.sessions.reset_plugin_sessions(plugin)

    def remove_host(self, fqdn):
        log.info("remove_host: %s" % fqdn)

        self.sessions.remove_host(fqdn)
        self.queues.remove_host(fqdn)
        self.hosts.remove_host(fqdn)

        with transaction.commit_on_success():
            for cert in ClientCertificate.objects.filter(host__fqdn = fqdn, revoked = False):
                log.info("Revoking %s:%s" % (fqdn, cert.serial))
                self.revoked_certs.add(cert.serial)
            ClientCertificate.objects.filter(host__fqdn = fqdn, revoked = False).update(revoked = True)

        # TODO: ensure there are no GETs left in progress after this completes
        # TODO: drain plugin_rx_queue so that anything we will send to AMQP has been sent before this returns

    def __init__(self):
        super(Service, self).__init__()

        self.queues = HostQueueCollection()
        self.sessions = SessionCollection(self.queues)
        self.hosts = HostStateCollection()
        self.revoked_certs = set()

        for cert in ClientCertificate.objects.filter(revoked = True):
            self.revoked_certs.add(cert.serial)

    def run(self):
        self.amqp_tx_forwarder = AmqpTxForwarder(self.queues)
        self.amqp_rx_forwarder = AmqpRxForwarder(self.queues)

        # This thread listens to an AMQP queue and appends incoming messages
        # to queues for retransmission to agents
        tx_svc_thread = ServiceThread(self.amqp_tx_forwarder)
        # This thread listens to local queues and appends received messages
        # to an AMQP queue
        rx_svc_thread = ServiceThread(self.amqp_rx_forwarder)
        rx_svc_thread.start()
        tx_svc_thread.start()

        # FIXME: this TERMINATE_ALL format could in principle
        # be passed back from the agent (but it should never
        # originate there), affecting sessions for other agents.

        # At restart, message receiving services to clear out any
        # existing session state (from a previous instance of this
        # service).
        for plugin in ['action_runner']:
            self.queues.receive({
                'fqdn': None,
                'type': 'SESSION_TERMINATE_ALL',
                'plugin': plugin,
                'session_id': None,
                'session_seq': None,
                'body': None
            })

        # This thread services session management RPCs, so that other
        # services can explicitly request a session reset
        session_rpc_thread = ServiceThread(HttpAgentRpc(self))
        session_rpc_thread.start()

        # Hook up the request handler
        MessageView.queues = self.queues
        MessageView.sessions = self.sessions
        MessageView.hosts = self.hosts
        MessageView.revoked_certs = self.revoked_certs

        # The thread for generating HostOfflineAlerts
        host_checker_thread = ServiceThread(HostStatePoller(self.hosts, self.sessions))
        host_checker_thread.start()

        # The main thread serves incoming requests to exchanges messages
        # with agents, until it is interrupted (gevent handles signals for us)
        self.server = gevent.wsgi.WSGIServer(('', HTTP_AGENT_PORT), WSGIHandler())
        self.server.serve_forever()

        session_rpc_thread.stop()
        tx_svc_thread.stop()
        rx_svc_thread.stop()
        host_checker_thread.stop()
        session_rpc_thread.join()
        tx_svc_thread.join()
        tx_svc_thread.join()
        host_checker_thread.join()

    def stop(self):
        self.server.stop()
