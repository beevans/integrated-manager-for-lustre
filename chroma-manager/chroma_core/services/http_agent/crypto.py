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


import urlparse
import os

from chroma_core.lib.util import CommandLine
from chroma_core.services import log_register
import re

import settings


class Crypto(CommandLine):
    # The manager's local key and certificate, used for
    # identifying itself to agents and to API clients such
    # as web browsers and the command line interface.
    MANAGER_KEY_FILE = os.path.join(settings.CRYPTO_FOLDER, 'manager.pem')
    MANAGER_CERT_FILE = os.path.join(settings.CRYPTO_FOLDER, 'manager.crt')

    # The local CA used for issuing certificates to agents, and
    # for signing the manager cert if an externally signed cert
    # is not provided
    AUTHORITY_KEY_FILE = os.path.join(settings.CRYPTO_FOLDER, 'authority.pem')
    AUTHORITY_CERT_FILE = os.path.join(settings.CRYPTO_FOLDER, 'authority.crt')

    # Certificate duration: we don't use expiration/reissue, so
    # this is set to a 'forever' value.
    CERTIFICATE_DAYS = "36500"

    log = log_register('crypto')

    def _get_or_create_private_key(self, filename):
        if not os.path.exists(filename):
            self.log.info("Generating manager key file")
            self.try_shell(['openssl', 'genrsa', '-out', filename, '2048'])
        return filename

    @property
    def authority_key(self):
        """
        Get the path to the authority key, or generate one
        """
        return self._get_or_create_private_key(self.AUTHORITY_KEY_FILE)

    @property
    def authority_cert(self):
        """
        Get the path to the authority certificate, or self-sign the authority key to generate one
        """
        if not os.path.exists(self.AUTHORITY_CERT_FILE):
            rc, csr, err = self.try_shell(["openssl", "req", "-new", "-subj", "/C=/ST=/L=/O=/CN=x_local_authority", "-key", self.authority_key])
            rc, out, err = self.try_shell(["openssl", "x509", "-req", "-days", self.CERTIFICATE_DAYS, "-signkey", self.authority_key, "-out", self.AUTHORITY_CERT_FILE], stdin_text = csr)

        return self.AUTHORITY_CERT_FILE

    @property
    def server_key(self):
        return self._get_or_create_private_key(self.MANAGER_KEY_FILE)

    @property
    def server_cert(self):
        if not os.path.exists(self.MANAGER_CERT_FILE):
            # Determine what domain name HTTP clients will
            # be using to access me, and bake that into my
            # certificate (using SERVER_HTTP_URL re
            hostname = urlparse.urlparse(settings.SERVER_HTTP_URL).hostname

            self.log.info("Generating manager certificate file")
            rc, csr, err = self.try_shell(["openssl", "req", "-new", "-subj", "/C=/ST=/L=/O=/CN=%s" % hostname, "-key", self.server_key])
            rc, out, err = self.try_shell(["openssl", "x509", "-req", "-days", self.CERTIFICATE_DAYS, "-CA", self.authority_cert, "-CAcreateserial", "-CAkey", self.authority_key, "-out", self.MANAGER_CERT_FILE], stdin_text = csr)

            self.log.info("Generated %s" % self.MANAGER_CERT_FILE)
        return self.MANAGER_CERT_FILE

    def get_common_name(self, csr_string):
        rc, out, err = self.try_shell(['openssl', 'req', '-noout', '-subject'], stdin_text = csr_string)
        return re.search("/CN=([^/]+)", out).group(1).strip()

    def sign(self, csr_string):
        self.log.info("Signing")

        rc, out, err = self.try_shell(["openssl", "x509", "-req", "-days", self.CERTIFICATE_DAYS, "-CAkey", self.authority_key, "-CA", self.authority_cert, "-CAcreateserial"], stdin_text = csr_string)
        return out.strip()

    def get_serial(self, cert_str):
        rc, out, err = self.try_shell(['openssl', 'x509', '-serial', '-noout'], stdin_text = cert_str)
        # Output like "serial=foo"
        return out.strip().split("=")[1]
