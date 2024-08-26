#! /usr/bin/env python

# /// script
# dependencies = [
#   "requests",
# ]
# ///

"""Generate a GitHub workload that runs `tox` on all published charms."""

import base64
import binascii
import json
import os
import subprocess

import requests


def _charmcraft_auth_to_macaroon(charmcraft_auth: str):
    """Decode charmcraft auth into the macaroon."""
    try:
        bytes = base64.b64decode(charmcraft_auth.strip().encode())
        return json.loads(bytes).get('v')
    except (binascii.Error, json.JSONDecodeError):
        return None


def macaroon() -> str:
    """Get the charmhub macaroon."""
    macaroon = os.environ.get('CHARM_MACAROON')
    charmcraft_auth = os.environ.get('CHARMCRAFT_AUTH')
    if not macaroon and charmcraft_auth:
        macaroon = _charmcraft_auth_to_macaroon(charmcraft_auth)
    if not macaroon:
        # Export to stderr because stdout gets a "Login successful" message.
        out = subprocess.run(
            ['charmcraft', 'login', '--export', '/dev/fd/2'],
            text=True,
            check=True,
            stderr=subprocess.PIPE,
        )
        macaroon = _charmcraft_auth_to_macaroon(out.stderr.splitlines()[-1])
    if not macaroon:
        raise ValueError('No charmhub macaroon found')
    return macaroon.strip()


def get_session():
    session = requests.Session()
    session.headers['Authorization'] = f'Macaroon {macaroon()}'
    session.headers['Content-Type'] = 'application/json'
    return session


def packages(session: requests.Session):
    # This works without being logged in, but we might as well re-use the session.
    resp = session.get('https://charmhub.io/packages.json')
    return resp.json()['packages']


def info(session: requests.Session, charm: str):
    """Get charm info."""
    resp = session.get(f'https://api.charmhub.io/v1/charm/{charm}').json()
    print(resp)


if __name__ == '__main__':
    session = get_session()
    for package in packages(session):
        info(session, package['name'])
        break
