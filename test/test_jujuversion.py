# Copyright 2019 Canonical Ltd.
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

import os
import unittest.mock  # in this file, importing just 'patch' would be confusing

import pytest

import ops


@pytest.mark.parametrize(
    'vs,major,minor,tag,patch,build',
    [
        ('0.0.0', 0, 0, '', 0, 0),
        ('0.0.2', 0, 0, '', 2, 0),
        ('0.1.0', 0, 1, '', 0, 0),
        ('0.2.3', 0, 2, '', 3, 0),
        ('10.234.3456', 10, 234, '', 3456, 0),
        ('10.234.3456.1', 10, 234, '', 3456, 1),
        ('1.21-alpha12', 1, 21, 'alpha', 12, 0),
        ('1.21-alpha1.34', 1, 21, 'alpha', 1, 34),
        ('2.7', 2, 7, '', 0, 0),
    ],
)
def test_parsing(vs: str, major: int, minor: int, tag: str, patch: int, build: int):
    v = ops.JujuVersion(vs)
    assert v.major == major
    assert v.minor == minor
    assert v.tag == tag
    assert v.patch == patch
    assert v.build == build


@unittest.mock.patch('os.environ', new={})
def test_from_environ():
    # JUJU_VERSION is not set
    v = ops.JujuVersion.from_environ()
    assert v == ops.JujuVersion('0.0.0')

    os.environ['JUJU_VERSION'] = 'no'
    with pytest.raises(RuntimeError, match='not a valid Juju version'):
        ops.JujuVersion.from_environ()

    os.environ['JUJU_VERSION'] = '2.8.0'
    v = ops.JujuVersion.from_environ()
    assert v == ops.JujuVersion('2.8.0')


def test_has_app_data():
    assert ops.JujuVersion('2.8.0').has_app_data()
    assert ops.JujuVersion('2.7.0').has_app_data()
    assert not ops.JujuVersion('2.6.9').has_app_data()


def test_is_dispatch_aware():
    assert ops.JujuVersion('2.8.0').is_dispatch_aware()
    assert not ops.JujuVersion('2.7.9').is_dispatch_aware()


def test_has_controller_storage():
    assert ops.JujuVersion('2.8.0').has_controller_storage()
    assert not ops.JujuVersion('2.7.9').has_controller_storage()


def test_has_secrets():
    assert ops.JujuVersion('3.0.3').has_secrets
    assert ops.JujuVersion('3.1.0').has_secrets
    assert not ops.JujuVersion('3.0.2').has_secrets
    assert not ops.JujuVersion('2.9.30').has_secrets


def test_supports_open_port_on_k8s():
    assert ops.JujuVersion('3.0.3').supports_open_port_on_k8s
    assert ops.JujuVersion('3.3.0').supports_open_port_on_k8s
    assert not ops.JujuVersion('3.0.2').supports_open_port_on_k8s
    assert not ops.JujuVersion('2.9.30').supports_open_port_on_k8s


def test_supports_exec_service_context():
    assert not ops.JujuVersion('2.9.30').supports_exec_service_context
    assert ops.JujuVersion('4.0.0').supports_exec_service_context
    assert not ops.JujuVersion('3.0.0').supports_exec_service_context
    assert not ops.JujuVersion('3.1.5').supports_exec_service_context
    assert ops.JujuVersion('3.1.6').supports_exec_service_context
    assert not ops.JujuVersion('3.2.0').supports_exec_service_context
    assert ops.JujuVersion('3.2.2').supports_exec_service_context
    assert ops.JujuVersion('3.3.0').supports_exec_service_context
    assert ops.JujuVersion('3.4.0').supports_exec_service_context


@pytest.mark.parametrize(
    'invalid_version',
    [
        'xyz',
        'foo.bar',
        'foo.bar.baz',
        'dead.beef.ca.fe',
        # The major version is too long.
        '1234567890.2.1',
        # Two periods next to each other.
        '0.2..1',
        # Tag comes after period.
        '1.21.alpha1',
        # No patch number but a tag is present.
        '1.21-alpha',
        # Non-numeric string after the patch number.
        '1.21-alpha1beta',
        # Tag duplication.
        '1.21-alpha-dev',
        # Underscore in a tag.
        '1.21-alpha_dev3',
        # Non-numeric string after the patch number.
        '1.21-alpha123dev3',
    ],
)
def test_parsing_errors(invalid_version: str):
    with pytest.raises(RuntimeError):
        ops.JujuVersion(invalid_version)


@pytest.mark.parametrize(
    'a,b,expected',
    [
        ('1.0.0', '1.0.0', True),
        ('01.0.0', '1.0.0', True),
        ('10.0.0', '9.0.0', False),
        ('1.0.0', '1.0.1', False),
        ('1.0.1', '1.0.0', False),
        ('1.0.0', '1.1.0', False),
        ('1.1.0', '1.0.0', False),
        ('1.0.0', '2.0.0', False),
        ('1.2-alpha1', '1.2.0', False),
        ('1.2-alpha2', '1.2-alpha1', False),
        ('1.2-alpha2.1', '1.2-alpha2', False),
        ('1.2-alpha2.2', '1.2-alpha2.1', False),
        ('1.2-beta1', '1.2-alpha1', False),
        ('1.2-beta1', '1.2-alpha2.1', False),
        ('1.2-beta1', '1.2.0', False),
        ('1.2.1', '1.2.0', False),
        ('2.0.0', '1.0.0', False),
        ('2.0.0.0', '2.0.0', True),
        ('2.0.0.0', '2.0.0.0', True),
        ('2.0.0.1', '2.0.0.0', False),
        ('2.0.1.10', '2.0.0.0', False),
    ],
)
def test_equality(a: str, b: str, expected: bool):
    assert (ops.JujuVersion(a) == ops.JujuVersion(b)) == expected
    assert (ops.JujuVersion(a) == b) == expected


@pytest.mark.parametrize(
    'a,b,expected_strict,expected_weak',
    [
        ('1.0.0', '1.0.0', False, True),
        ('01.0.0', '1.0.0', False, True),
        ('10.0.0', '9.0.0', False, False),
        ('1.0.0', '1.0.1', True, True),
        ('1.0.1', '1.0.0', False, False),
        ('1.0.0', '1.1.0', True, True),
        ('1.1.0', '1.0.0', False, False),
        ('1.0.0', '2.0.0', True, True),
        ('1.2-alpha1', '1.2.0', True, True),
        ('1.2-alpha2', '1.2-alpha1', False, False),
        ('1.2-alpha2.1', '1.2-alpha2', False, False),
        ('1.2-alpha2.2', '1.2-alpha2.1', False, False),
        ('1.2-beta1', '1.2-alpha1', False, False),
        ('1.2-beta1', '1.2-alpha2.1', False, False),
        ('1.2-beta1', '1.2.0', True, True),
        ('1.2.1', '1.2.0', False, False),
        ('2.0.0', '1.0.0', False, False),
        ('2.0.0.0', '2.0.0', False, True),
        ('2.0.0.0', '2.0.0.0', False, True),
        ('2.0.0.1', '2.0.0.0', False, False),
        ('2.0.1.10', '2.0.0.0', False, False),
        ('2.10.0', '2.8.0', False, False),
    ],
)
def test_comparison(a: str, b: str, expected_strict: bool, expected_weak: bool):
    assert (ops.JujuVersion(a) < ops.JujuVersion(b)) == expected_strict
    assert (ops.JujuVersion(a) <= ops.JujuVersion(b)) == expected_weak
    assert (ops.JujuVersion(b) > ops.JujuVersion(a)) == expected_strict
    assert (ops.JujuVersion(b) >= ops.JujuVersion(a)) == expected_weak
    # Implicit conversion.
    assert (ops.JujuVersion(a) < b) == expected_strict
    assert (ops.JujuVersion(a) <= b) == expected_weak
    assert (b > ops.JujuVersion(a)) == expected_strict
    assert (b >= ops.JujuVersion(a)) == expected_weak
