# Copyright 2020 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
import json
import yaml
import cryptography

from ops import framework
from ops.charm import CharmBase
from ops import testing
from ops import model

from ops.lib.tls_certificates import ca_client
from pathlib import Path


class TestCAClient(unittest.TestCase):

    def setUp(self):
        self.harness = testing.Harness(CharmBase, meta='''
            name: myserver
            peers:
              ca-client:
                interface: tls-certificates
        ''')

        self.harness.begin()
        self.ca_client = ca_client.CAClient(self.harness.charm, 'ca-client')

    def test_is_join(self):

        class TestReceiver(framework.Object):

            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.observed_events = []

            def on_ca_available(self, event):
                self.observed_events.append(event)

        receiver = TestReceiver(self.harness.framework, 'receiver')
        self.harness.framework.observe(self.ca_client.on.ca_available, receiver)

        relation_id = self.harness.add_relation('ca-client', 'easyrsa')
        self.assertTrue(self.ca_client.is_joined)

        self.harness.add_relation_unit(relation_id, 'easyrsa/0',
                                       {'ingress-address': '192.0.2.2'})

        self.assertTrue(len(receiver.observed_events) == 1)
        self.assertIsInstance(receiver.observed_events[0], ca_client.CAAvailable)

    def test_request_server_certificate(self):
        relation_id = self.harness.add_relation('ca-client', 'easyrsa')

        self.harness.update_relation_data(
            relation_id, 'myserver/0', {'ingress-address': '192.0.2.1'})

        self.harness.add_relation_unit(relation_id, 'easyrsa/0',
                                       {'ingress-address': '192.0.2.2'})
        rel = self.harness.charm.model.get_relation('ca-client')

        # Cannot obtain {certificate, key, ca_certificate} before a request is made.
        with self.assertRaises(ca_client.CAClientError) as cm:
            self.ca_client.certificate
        self.assertIsInstance(cm.exception.status, model.BlockedStatus)

        with self.assertRaises(ca_client.CAClientError) as cm:
            self.ca_client.key
        self.assertIsInstance(cm.exception.status, model.BlockedStatus)

        with self.assertRaises(ca_client.CAClientError) as cm:
            self.ca_client.ca_certificate
        self.assertIsInstance(cm.exception.status, model.BlockedStatus)

        example_hostname = 'myserver.example'
        sans = [example_hostname, '192.0.2.1']
        self.ca_client.request_server_certificate(example_hostname, sans)

        server_data = rel.data[self.harness.charm.model.unit]
        self.assertEqual(server_data['common_name'], example_hostname)
        self.assertEqual(server_data['sans'], json.dumps(sans))

        # Waiting for more relation data now - check for WaitingStatus in the exception.
        with self.assertRaises(ca_client.CAClientError) as cm:
            self.ca_client.certificate
        self.assertIsInstance(cm.exception.status, model.WaitingStatus)

        with self.assertRaises(ca_client.CAClientError) as cm:
            self.ca_client.key
        self.assertIsInstance(cm.exception.status, model.WaitingStatus)

        with self.assertRaises(ca_client.CAClientError) as cm:
            self.ca_client.ca_certificate
        self.assertIsInstance(cm.exception.status, model.WaitingStatus)

        # Simulate a change and make sure it propagates to relation data correctly.
        new_example_hostname = 'myserver1.example'
        new_sans = [new_example_hostname, '192.0.2.10']
        self.ca_client.request_server_certificate(new_example_hostname, new_sans)
        self.assertEqual(server_data['common_name'], new_example_hostname)
        self.assertEqual(server_data['sans'], json.dumps(new_sans))

    def test__on_relation_changed(self):

        class TestReceiver(framework.Object):

            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.observed_events = []

            def on_tls_config_ready(self, event):
                self.observed_events.append(event)

        receiver = TestReceiver(self.harness.framework, 'receiver')
        self.harness.framework.observe(self.ca_client.on.tls_config_ready, receiver)

        relation_id = self.harness.add_relation('ca-client', 'easyrsa')
        self.harness.update_relation_data(relation_id, 'myserver/0',
                                          {'ingress-address': '10.209.240.176'})

        self.harness.add_relation_unit(relation_id, 'easyrsa/0', {'ingress-address': '192.0.2.2'})

        self.harness.update_relation_data(
            relation_id, 'myserver/0', {
                'ingress-address': '10.209.240.176',
                'common_name': '10.209.240.176',
                'sans': '10.209.240.176',
            }
        )
        # Load the sample relation data from a file. The certificates and a key
        # were generated once for the purposes of creating an example.
        # They are not used anywhere in a production or test system.
        ca_client_data = yaml.safe_load(
            (Path(__file__).parent / 'ca_client_test_data.yaml').read_text())

        self.harness.update_relation_data(relation_id, 'easyrsa/0', ca_client_data)

        self.assertTrue(len(receiver.observed_events) == 1)
        self.assertIsInstance(receiver.observed_events[0], ca_client.TlsConfigReady)

        self.assertIsInstance(self.ca_client.ca_certificate,
                              cryptography.hazmat.backends.openssl.x509._Certificate)
        self.assertIsInstance(self.ca_client.certificate,
                              cryptography.hazmat.backends.openssl.x509._Certificate)
        self.assertIsInstance(self.ca_client.key,
                              cryptography.hazmat.backends.openssl.rsa._RSAPrivateKey)

        self.assertTrue(self.ca_client.is_ready)


if __name__ == "__main__":
    unittest.main()
