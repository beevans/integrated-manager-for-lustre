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


import Queue
import json
import traceback
import datetime
import dateutil
import dateutil.tz

from django.db import transaction
from django.http import HttpResponseNotAllowed, HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from functools import wraps
import settings
import os
from tastypie.http import HttpForbidden

from chroma_core.models import ManagedHost, ClientCertificate, RegistrationToken
from chroma_core.models.utils import Version
from chroma_core.services import log_register
from chroma_core.services.http_agent.crypto import Crypto


log = log_register('agent_views')


def log_exception(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        try:
            return f(*args)
        except Exception:
            log.error(traceback.format_exc())
            raise

    return wrapped


class MessageView(View):
    queues = None
    sessions = None
    hosts = None

    LONG_POLL_TIMEOUT = 30

    @classmethod
    def valid_fqdn(cls, request):
        "Return fqdn if certificate is valid."
        fqdn = cls.valid_certs.get(request.META['HTTP_X_SSL_CLIENT_SERIAL'])
        if not fqdn:
            log.warning("Rejecting certificate %s" % request.META['HTTP_X_SSL_CLIENT_SERIAL'])
        elif fqdn != request.META['HTTP_X_SSL_CLIENT_NAME']:
            log.info("Domain name changed %s" % fqdn)
        return fqdn

    @log_exception
    def post(self, request):
        """
        Receive messages FROM the agent.
        Handle a POST containing messages from the agent
        """

        body = json.loads(request.body)
        fqdn = self.valid_fqdn(request)
        if not fqdn:
            return HttpForbidden()

        try:
            messages = body['messages']
        except KeyError:
            return HttpResponseBadRequest("Missing attribute 'messages'")

        # Check that the server identifier in each message
        # is valid by comparing against the SSL_CLIENT_NAME
        # which is cryptographically vouched for at the HTTPS frontend
        for message in messages:
            if message['fqdn'] != fqdn:
                return HttpResponseBadRequest("Incorrect client name")

        log.debug("MessageView.post: %s %s messages: %s" % (fqdn, len(messages), body))
        for message in messages:
            if message['type'] == 'DATA':
                try:
                    self.sessions.get(fqdn, message['plugin'], message['session_id'])
                except KeyError:
                    log.warning("Terminating session because unknown %s/%s/%s" % (fqdn, message['plugin'], message['session_id']))
                    self.queues.send({
                        'fqdn': fqdn,
                        'type': 'SESSION_TERMINATE',
                        'plugin': message['plugin'],
                        'session_id': None,
                        'session_seq': None,
                        'body': None
                    })
                else:
                    log.debug("Forwarding valid message %s/%s/%s-%s" % (fqdn, message['plugin'], message['session_id'], message['session_seq']))
                    self.queues.receive(message)

            elif message['type'] == 'SESSION_CREATE_REQUEST':
                session = self.sessions.create(fqdn, message['plugin'])
                log.info("Creating session %s/%s/%s" % (fqdn, message['plugin'], session.id))

                # When creating a session, it may be for a new agent instance.  There may be an older
                # agent instance with a hanging GET.  We need to make sure that messages that we send
                # from this point onwards go to the new agent and not any GET handlers that haven't
                # caught up yet.  Achive this by sending a barrier message with the agent start time, such
                # that any GET handler receiving the barrier which has a different agent start time will
                # detach itself from the TX queue.  NB the barrier only works because there's also a lock,
                # so if there was a zombie GET, it will be holding the lock and receive the barrier.

                self.queues.send({
                    'fqdn': fqdn,
                    'type': 'TX_BARRIER',
                    'client_start_time': body['client_start_time']
                })

                self.queues.send({
                    'fqdn': fqdn,
                    'type': 'SESSION_CREATE_RESPONSE',
                    'plugin': session.plugin,
                    'session_id': session.id,
                    'session_seq': None,
                    'body': None
                })

        return HttpResponse()

    def _filter_valid_messages(self, fqdn, messages):
        plugin_to_session_id = {}

        def is_valid(message):
            try:
                session_id = plugin_to_session_id[message['plugin']]
            except KeyError:
                try:
                    plugin_to_session_id[message['plugin']] = session_id = self.sessions.get(fqdn, message['plugin']).id
                except KeyError:
                    plugin_to_session_id[message['plugin']] = session_id = None

            if message['session_id'] != session_id:
                log.debug("Dropping message because it has stale session id (current is %s): %s" % (session_id, message))
                return False

            return True

        return [m for m in messages if is_valid(m)]

    @log_exception
    def get(self, request):
        """
        Send messages TO the agent.
        Handle a long-polling GET for messages to the agent
        """

        fqdn = self.valid_fqdn(request)
        if not fqdn:
            return HttpForbidden()
        server_boot_time = dateutil.parser.parse(request.GET['server_boot_time'])
        client_start_time = dateutil.parser.parse(request.GET['client_start_time'])

        messages = []

        try:
            reset_required = self.hosts.update(fqdn, server_boot_time, client_start_time)
        except ManagedHost.DoesNotExist:
            # This should not happen because the HTTPS frontend should have the
            # agent certificate revoked before removing the ManagedHost from the database
            log.error("GET from unknown server %s" % fqdn)
            return HttpResponseBadRequest("Unknown server '%s'" % fqdn)

        if reset_required:
            # This is the case where the http_agent service restarts, so
            # we have to let the agent know that all open sessions
            # are now over.
            messages.append({
                'fqdn': fqdn,
                'type': 'SESSION_TERMINATE_ALL',
                'plugin': None,
                'session_id': None,
                'session_seq': None,
                'body': None
            })

        log.debug("MessageView.get: composing messages for %s" % fqdn)
        queues = self.queues.get(fqdn)

        # If this handler is sitting on the TX queue, draining messages, then
        # when a new session starts, *before* sending any TX messages, we have to
        # make sure it has been disconnected, to avoid the TX messages being sent
        # to an 'old' session (old session meaning TCP connection from a now-dead agent)

        with queues.tx_lock:
            try:
                first_message = queues.tx.get(block=True, timeout=self.LONG_POLL_TIMEOUT)
                if first_message['type'] == 'TX_BARRIER':
                    if first_message['client_start_time'] != request.GET['client_start_time']:
                        log.warning("Cancelling GET due to barrier %s %s" % (first_message['client_start_time'], request.GET['client_start_time']))
                        return HttpResponse(json.dumps({'messages': []}), mimetype="application/json")
                else:
                    messages.append(first_message)
            except Queue.Empty:
                pass
            else:
                # TODO: limit number of messages per response
                while True:
                    try:
                        message = queues.tx.get(block=False)
                        if message['type'] == 'TX_BARRIER':
                            if message['client_start_time'] != request.GET['client_start_time']:
                                log.warning("Cancelling GET due to barrier %s %s" % (message['client_start_time'], request.GET['client_start_time']))
                                return HttpResponse(json.dumps({'messages': []}), mimetype="application/json")
                        else:
                            messages.append(message)
                    except Queue.Empty:
                        break

        messages = self._filter_valid_messages(fqdn, messages)

        log.debug("MessageView.get: responding to %s with %s messages (%s)" % (fqdn, len(messages), client_start_time))
        return HttpResponse(json.dumps({'messages': messages}), mimetype = "application/json")


setup_script_template = """
import sys, httplib, urllib2, shlex, base64, json, os, socket, ssl, tempfile, json, traceback
from subprocess import Popen, PIPE

SSL_DIR = "/var/lib/chroma/"

# The agent's private key, never shared
PRIVATE_KEY = os.path.join(SSL_DIR, 'private.pem')

# The agent's certificate, generated by the manager in response to a CSR
AGENT_CERT = os.path.join(SSL_DIR, 'self.crt')

# The root certificate used to authenticate the manager
AUTHORITY_CERT = os.path.join(SSL_DIR, 'authority.crt')


REPO_PATH = "/etc/yum.repos.d/Intel-Lustre-Agent.repo"



base_url = "{base_url}"
reg_url = "{reg_url}"
cert_str = '''{cert_str}'''
repo_url = "{repo_url}"

REPO_CONTENT = \"\"\"{repos}\"\"\"


class VerifiedHTTPSConnection(httplib.HTTPSConnection):
    def connect(self):
        sock = socket.create_connection((self.host, self.port), self.timeout)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
        self.sock = ssl.wrap_socket(sock, cert_reqs=ssl.CERT_REQUIRED, ca_certs=AUTHORITY_CERT)


class VerifiedHTTPSHandler(urllib2.HTTPSHandler):
    def __init__(self, connection_class = VerifiedHTTPSConnection):
        self.specialized_conn_class = connection_class
        urllib2.HTTPSHandler.__init__(self)
    def https_open(self, req):
        return self.do_open(self.specialized_conn_class, req)


def launch_command(cmd):
    args = shlex.split(cmd)
    p = Popen(args, stdout=PIPE)
    stdout = p.communicate()[0]
    if p.returncode != 0:
        raise Exception("Error running command: %s" % cmd)
    return stdout.strip()


def setup_keys():
    if not os.path.exists(SSL_DIR):
        os.makedirs(SSL_DIR)

    with open(AUTHORITY_CERT, 'w') as f:
        f.write(cert_str)

    return launch_command('openssl genrsa -out %s 2048' % PRIVATE_KEY)


def reg_manager():
    fqdn = socket.getfqdn()
    nodename = os.uname()[1]
    csr = launch_command("openssl req -new -subj /C=/ST=/L=/O=/CN=%s -key %s" % (fqdn, PRIVATE_KEY))

    data = json.dumps({{
        'address': socket.gethostbyname(socket.gethostname()),
        'fqdn': fqdn,
        'nodename': nodename,
        'version': 0,
        'csr': csr,
        'capabilities': []
        }})

    try:
        https_handler = VerifiedHTTPSHandler()
        url_opener = urllib2.build_opener(https_handler)
        url_opener.addheaders.append(('Content-Type', 'application/json'))
        handle = url_opener.open(reg_url, data)
        response = handle.readlines()
        handle.close()

        json_resp = json.loads(response[0])
        open(AGENT_CERT, 'w').write(json_resp['certificate'])
        return json_resp
    except urllib2.URLError, e:
        print traceback.format_exc()
        sys.exit("Cannot reach host/url %s: %s" % (reg_url, e))


def create_repo():
    tmp = tempfile.NamedTemporaryFile()
    tmp.write(REPO_CONTENT.format(repo_url, AUTHORITY_CERT, PRIVATE_KEY, AGENT_CERT))

    tmp.flush()
    launch_command('cp %s %s' % (tmp.name, REPO_PATH))
    os.chmod(REPO_PATH, 0644)


def install_agent():
    return launch_command('yum install -y chroma-agent-management')


def configure_server():
    server_conf_path = '/var/lib/chroma'
    launch_command('mkdir -p %s' % server_conf_path)
    tmp = tempfile.NamedTemporaryFile()
    tmp.write(json.dumps({{'url': base_url + "agent/"}}))
    tmp.flush()
    launch_command('cp %s %s' % (tmp.name, os.path.join(server_conf_path, 'server_conf')))


def start_agent():
    output = launch_command("/sbin/chkconfig chroma-agent on")
    output = launch_command("/sbin/service chroma-agent start")


if __name__ == '__main__':
    # Set up SSL keys and register with the manager using our
    # embedded registration token
    setup_keys()
    registration_response = reg_manager()

    # Now that we're registered, we can download packages
    create_repo()
    install_agent()

    # Persist the agent configuration file so that it can connect
    # to the manager
    configure_server()

    # Finally start the agent, it will take it from here.
    start_agent()

    print json.dumps({{'host_id': registration_response['host_id'], 'command_id': registration_response['command_id']}})
"""


def validate_token(key, credits=1):
    """
    Validate that a token is valid to authorize a setup/register operation:
     * Check it's not expired
     * Check it has some credits

    :param credits: number of credits to decrement if valid
    :return 2-tuple (<http response if error, else None>, <registration token if valid, else None>)
    """
    try:
        with transaction.commit_on_success():
            token = RegistrationToken.objects.get(secret = key)
            if not token.credits:
                log.warning("Attempt to register with exhausted token %s" % key)
                return HttpForbidden(), None
            else:
                # Decrement .credits
                RegistrationToken.objects.filter(secret = key).update(credits = token.credits - credits)
    except RegistrationToken.DoesNotExist:
        log.warning("Attempt to register with non-existent token %s" % key)
        return HttpForbidden(), None
    else:
        now = datetime.datetime.utcnow()
        now = now.replace(tzinfo = dateutil.tz.tzutc())

        if token.expiry < now:
            log.warning("Attempt to register with expired token %s (now %s, expired at %s)" % (key, now, token.expiry))
            return HttpForbidden(), None
        elif token.cancelled:
            log.warning("Attempt to register with cancelled token %s" % key)
            return HttpForbidden(), None

    return None, token


@csrf_exempt
@log_exception
def setup(request, key):
    token_error, token = validate_token(key, credits=0)
    if token_error:
        return token_error

    repos = ""
    for bundle in token.profile.bundles.all():
        repos += """[%s]
name=%s
baseurl={0}/%s
enabled=1
gpgcheck=0
sslverify = 1
sslcacert = {1}
sslclientkey = {2}
sslclientcert = {3}
proxy=_none_

""" % (bundle.bundle_name, bundle.description, bundle.bundle_name)

    base_url = str(settings.SERVER_HTTP_URL)
    reg_url = os.path.join(base_url, 'agent/register/%s/' % key)
    repo_url = os.path.join(base_url, 'repo/')
    crypto = Crypto()
    cert_str = open(crypto.AUTHORITY_CERT_FILE).read()
    script_formatted = setup_script_template.format(reg_url = reg_url, cert_str = cert_str,
                                                    repo_url= repo_url, base_url = base_url,
                                                    repos = repos)

    return HttpResponse(status = 201, content = script_formatted)


@csrf_exempt
@log_exception
def register(request, key):
    if request.method != "POST":
        return HttpResponseNotAllowed(['POST'])

    token_error, registration_token = validate_token(key)
    if token_error:
        return token_error

    host_attributes = json.loads(request.body)

    # Fail at the first if the version of the agent on the server is incorrect
    manager, agent = Version(settings.VERSION), Version(host_attributes['version'])
    if manager and agent and not (manager.major == agent.major and manager.minor >= agent.minor):
        err = "Version incompatibility between manager {0} and agent {1}".format(manager, agent)
        log.error(err)
        return HttpResponse(status = 400, content = err)

    # Fulfil the registering server's request for a certificate authenticating
    # it as the owner of this FQDN.
    csr = host_attributes['csr']

    # Check that the commonName in the CSR is the same as that in host_attributes
    # (prevent registering as one host and getting a certificate to impersonate another)
    csr_fqdn = Crypto().get_common_name(csr)
    if csr_fqdn != host_attributes['fqdn']:
        # Terse response to attacker
        log.error("FQDN mismatch '%s' vs. '%s' from %s" % (csr_fqdn, host_attributes['fqdn'], request.META['HTTP_X_FORWARDED_FOR']))
        return HttpResponse(status = 400, content = "")

    with transaction.commit_on_success():
        # Isolate transaction to avoid locking ManagedHost table, this
        # is just a friendly pre-check and will be enforced again inside
        # job_scheduler.create_host
        try:
            existing_host = ManagedHost.objects.get(fqdn=host_attributes['fqdn'])
        except ManagedHost.DoesNotExist:
            pass
        else:
            if existing_host.state != 'undeployed':
                return HttpResponse(status=400, content=json.dumps({'fqdn': ["FQDN in use"]}))

    certificate_str = Crypto().sign(csr)
    certificate_serial = Crypto().get_serial(certificate_str)
    log.info("Generated certificate %s:%s" % (host_attributes['fqdn'], certificate_serial))
    MessageView.valid_certs[certificate_serial] = host_attributes['fqdn']

    # FIXME: handle the case where someone registers,
    # and then dies before saving their certificate:
    # when they come through here again, currently
    # we'll reject them because the FQDN is taken
    # ... maybe hand back the certificate here, but
    # then don't create the host until they first
    # connect using the certificate?
    # in that case to avoid handing out another cert
    # to someone else spamming our URL, we should have
    # some logic during the second addition to revoke
    # the first (should never be used) host cert.

    server_profile = registration_token.profile
    from chroma_core.services.job_scheduler.job_scheduler_client import JobSchedulerClient

    host, command = JobSchedulerClient.create_host(
        address=host_attributes['address'],
        fqdn=host_attributes['fqdn'],
        nodename=host_attributes['nodename'],
        server_profile_id=server_profile.pk
    )

    with transaction.commit_on_success():
        ClientCertificate.objects.create(host = host, serial = certificate_serial)

    # TODO: document this return format
    return HttpResponse(status = 201, content = json.dumps({
        'command_id': command.id,
        'host_id': host.id,
        'certificate': certificate_str
    }), mimetype = "application/json")


@csrf_exempt
@log_exception
def reregister(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    fqdn = MessageView.valid_fqdn(request)
    if not fqdn:
        return HttpForbidden()
    host_attributes = json.loads(request.body)

    MessageView.valid_certs[request.META['HTTP_X_SSL_CLIENT_SERIAL']] = host_attributes['fqdn']
    ManagedHost.objects.filter(fqdn=fqdn).update(fqdn=host_attributes['fqdn'], address=host_attributes['address'])
    return HttpResponse()
