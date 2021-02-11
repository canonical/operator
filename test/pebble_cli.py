# Copyright 2021 Canonical Ltd.
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

"""Pebble command-line interface (CLI) for local testing.

Usage examples:

python -m test.pebble_cli -h
python -m test.pebble_cli --socket=pebble_dir/.pebble.socket system-info
PEBBLE=pebble_dir python -m test.pebble_cli system-info
"""

import argparse
import datetime
import os
import sys

from ops import pebble


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', help='pebble socket path, default $PEBBLE/.pebble.socket')
    subparsers = parser.add_subparsers(dest='command', metavar='command')

    p = subparsers.add_parser('abort', help='abort a change by ID')
    p.add_argument('change_id', help='ID of change to abort')

    p = subparsers.add_parser('ack', help='acknowledge warnings up to given time')
    p.add_argument('--timestamp', help='time to acknowledge up to (YYYY-mm-ddTHH:MM:SS.f+ZZ:zz'
                                       'format), default current time',
                   type=pebble._parse_timestamp)

    p = subparsers.add_parser('autostart', help='autostart default service(s)')

    p = subparsers.add_parser('change', help='show a single change by ID')
    p.add_argument('change_id', help='ID of change to fetch')

    p = subparsers.add_parser('changes', help='show (filtered) changes')
    p.add_argument('--select', help='change state to filter on, default %(default)s',
                   choices=[s.value for s in pebble.ChangeState], default='all')
    p.add_argument('--service', help='optional service name to filter on')

    p = subparsers.add_parser('start', help='start service(s)')
    p.add_argument('service', help='name of service to start (can specify multiple)', nargs='+')

    p = subparsers.add_parser('stop', help='stop service(s)')
    p.add_argument('service', help='name of service to stop (can specify multiple)', nargs='+')

    p = subparsers.add_parser('system-info', help='show Pebble system information')

    p = subparsers.add_parser('warnings', help='show (filtered) warnings')
    p.add_argument('--select', help='warning state to filter on, default %(default)s',
                   choices=[s.value for s in pebble.WarningState], default='all')

    args = parser.parse_args()

    if not args.command:
        parser.error('argument command: required')

    socket_path = args.socket
    if socket_path is None:
        pebble_env = os.getenv('PEBBLE')
        if not pebble_env:
            print('cannot create Pebble client (set PEBBLE or specify --socket)', file=sys.stderr)
            sys.exit(1)
        socket_path = os.path.join(pebble_env, '.pebble.socket')

    client = pebble.Client(socket_path=socket_path)

    try:
        if args.command == 'abort':
            result = client.abort_change(pebble.ChangeID(args.change_id))
        elif args.command == 'ack':
            timestamp = args.timestamp or datetime.datetime.now(tz=datetime.timezone.utc)
            result = client.ack_warnings(timestamp)
        elif args.command == 'autostart':
            result = client.autostart_services()
        elif args.command == 'change':
            result = client.get_change(pebble.ChangeID(args.change_id))
        elif args.command == 'changes':
            result = client.get_changes(select=pebble.ChangeState(args.select),
                                        service=args.service)
        elif args.command == 'start':
            result = client.start_services(args.service)
        elif args.command == 'stop':
            result = client.stop_services(args.service)
        elif args.command == 'system-info':
            result = client.get_system_info()
        elif args.command == 'warnings':
            result = client.get_warnings(select=pebble.WarningState(args.select))
        else:
            raise AssertionError("shouldn't happen")
    except pebble.APIError as e:
        print('{} {}: {}'.format(e.code, e.status, e.message), file=sys.stderr)
        sys.exit(1)
    except pebble.ConnectionError as e:
        print('cannot connect to socket {!r}: {}'.format(socket_path, e),
              file=sys.stderr)
        sys.exit(1)
    except pebble.ServiceError as e:
        print('ServiceError:', e, file=sys.stderr)
        sys.exit(1)

    if isinstance(result, list):
        for x in result:
            print(x)
    else:
        print(result)


if __name__ == '__main__':
    main()
