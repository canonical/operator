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
import typing

from ops import pebble
from ops._private import timeconv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', help='pebble socket path, default $PEBBLE/.pebble.socket')
    subparsers = parser.add_subparsers(dest='command', metavar='command')

    p = subparsers.add_parser('abort', help='abort a change by ID')
    p.add_argument('change_id', help='ID of change to abort')

    p = subparsers.add_parser('ack', help='acknowledge warnings up to given time')
    p.add_argument(
        '--timestamp',
        help='time to acknowledge up to (YYYY-mm-ddTHH:MM:SS.f+ZZ:zzformat), default current time',
        type=timeconv.parse_rfc3339,
    )

    p = subparsers.add_parser('add', help='add a configuration layer dynamically')
    p.add_argument('--combine', action='store_true', help='combine layer instead of appending')
    p.add_argument('label', help='label for new layer')
    p.add_argument('layer_path', help='path of layer YAML file')

    p = subparsers.add_parser('autostart', help='autostart default service(s)')

    p = subparsers.add_parser('change', help='show a single change by ID')
    p.add_argument('change_id', help='ID of change to fetch')

    p = subparsers.add_parser('changes', help='show (filtered) changes')
    p.add_argument(
        '--select',
        help='change state to filter on, default %(default)s',
        choices=[s.value for s in pebble.ChangeState],
        default='all',
    )
    p.add_argument('--service', help='optional service name to filter on')

    p = subparsers.add_parser('checks', help='show (filtered) checks')
    p.add_argument(
        '--level',
        help='check level to filter on, default all levels',
        choices=[c.value for c in pebble.CheckLevel],
        default='',
    )
    p.add_argument('name', help='check name(s) to filter on', nargs='*')

    p = subparsers.add_parser('exec', help='execute a command')
    p.add_argument('--context', help='service context')
    p.add_argument(
        '--env', help='environment variables to set', action='append', metavar='KEY=VALUE'
    )
    p.add_argument('--working-dir', help='working directory to run command in')
    p.add_argument(
        '--io-mode',
        help='input/output mode, default %(default)r',
        choices=['passthrough', 'string'],
        default='passthrough',
    )
    p.add_argument('-t', '--timeout', type=float, help='timeout in seconds')
    p.add_argument('-u', '--user', help='user to run as')
    p.add_argument('-g', '--group', help='group to run as')
    p.add_argument(
        '--encoding', help="input/output encoding or 'none', default %(default)r", default='utf-8'
    )
    p.add_argument('--combine-stderr', help='combine stderr into stdout', action='store_true')
    p.add_argument('exec_command', help='command and arguments', nargs='+', metavar='command')

    p = subparsers.add_parser('ls', help='list files')
    p.add_argument(
        '-d',
        '--directory',
        action='store_true',
        help='list directories themselves, not their contents',
    )
    p.add_argument('-p', '--pattern', help='glob pattern to filter results')
    p.add_argument('path', help='name of directory or file')

    p = subparsers.add_parser('mkdir', help='create directory')
    p.add_argument(
        '-p', '--parents', action='store_true', help='create parent directories if needed'
    )
    p.add_argument('path', help='path to create')

    p = subparsers.add_parser('plan', help='show configuration plan (combined layers)')

    p = subparsers.add_parser('pull', help='copy file from remote system')
    p.add_argument('remote_path', help='path of remote file')
    p.add_argument('local_path', help='path of local file to copy to')

    p = subparsers.add_parser('push', help='copy file to remote system')
    p.add_argument('-d', '--dirs', action='store_true', help='create parent directories')
    p.add_argument('-m', '--mode', help='3-digit octal permissions')
    p.add_argument('-u', '--user', help='user to set')
    p.add_argument('-g', '--group', help='group to set')
    p.add_argument('local_path', help='path of local file')
    p.add_argument('remote_path', help='path of remote file to copy to')

    p = subparsers.add_parser('rm', help='remove path')
    p.add_argument(
        '-r', '--recursive', action='store_true', help='recursively delete directory contents'
    )
    p.add_argument('path', help='path to remove')

    p = subparsers.add_parser('services', help='show service status')
    p.add_argument('service', help='name of service (none means all; multiple ok)', nargs='*')

    p = subparsers.add_parser('start', help='start service(s)')
    p.add_argument('service', help='name of service to start (can specify multiple)', nargs='+')

    p = subparsers.add_parser('stop', help='stop service(s)')
    p.add_argument('service', help='name of service to stop (can specify multiple)', nargs='+')

    p = subparsers.add_parser('system-info', help='show Pebble system information')

    p = subparsers.add_parser('wait', help='wait for a change by ID')
    p.add_argument('-t', '--timeout', type=float, help='timeout in seconds')
    p.add_argument('change_id', help='ID of change to wait for')

    p = subparsers.add_parser('warnings', help='show (filtered) warnings')
    p.add_argument(
        '--select',
        help='warning state to filter on, default %(default)s',
        choices=[s.value for s in pebble.WarningState],
        default='all',
    )

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
        elif args.command == 'add':
            try:
                with open(args.layer_path, encoding='utf-8') as f:
                    layer_yaml = f.read()
            except OSError as e:
                parser.error(f'cannot read layer YAML: {e}')
            client.add_layer(args.label, layer_yaml, combine=bool(args.combine))
            result = f'Layer {args.label!r} added successfully from {args.layer_path!r}'
        elif args.command == 'autostart':
            result = client.autostart_services()
        elif args.command == 'change':
            result = client.get_change(pebble.ChangeID(args.change_id))
        elif args.command == 'changes':
            result = client.get_changes(
                select=pebble.ChangeState(args.select), service=args.service
            )
        elif args.command == 'checks':
            result = client.get_checks(level=pebble.CheckLevel(args.level), names=args.name)
        elif args.command == 'exec':
            environment = {}
            for env in typing.cast(typing.List[str], args.env) or []:
                key, _, value = env.partition('=')
                environment[key] = value

            encoding = args.encoding if args.encoding != 'none' else None
            if args.io_mode == 'passthrough':
                if encoding is not None:
                    stdin = sys.stdin
                    stdout = sys.stdout
                    stderr = sys.stderr if not args.combine_stderr else None
                else:
                    stdin = sys.stdin.buffer
                    stdout = sys.stdout.buffer
                    stderr = sys.stderr.buffer if not args.combine_stderr else None
            else:
                if sys.stdin.isatty():
                    stdin = sys.stdin.buffer if encoding is None else sys.stdin
                else:
                    stdin = sys.stdin.buffer.read() if encoding is None else sys.stdin.read()
                stdout = None
                stderr = None

            process = client.exec(  # type: ignore
                args.exec_command,
                service_context=args.context,
                environment=environment,
                working_dir=args.working_dir,
                timeout=args.timeout,
                user=args.user,
                group=args.group,
                stdin=stdin,  # type: ignore
                stdout=stdout,  # type: ignore
                stderr=stderr,  # type: ignore
                encoding=encoding,
                combine_stderr=args.combine_stderr,
            )
            # `process` might actually be a pebble.ExecProcess[bytes].
            # However, for the use we are making of it - particularly of `.stdout` and `.stderr` -
            # it does not make any difference. Unfortunately, pyright complains when we call
            # `wait()` and `wait_output()` if we do not make the generic concrete here.
            process = typing.cast(pebble.ExecProcess[str], process)

            try:
                if args.io_mode == 'passthrough':
                    process.wait()
                else:
                    stdout, stderr = process.wait_output()
                    print(repr(stdout))
                    if stderr:
                        print(repr(stderr), end='', file=sys.stderr)
                sys.exit(0)
            except pebble.ExecError as e:  # type: ignore
                print('ExecError:', e, file=sys.stderr)  # type: ignore
                sys.exit(e.exit_code)

        elif args.command == 'ls':
            result = client.list_files(args.path, pattern=args.pattern, itself=args.directory)
        elif args.command == 'mkdir':
            client.make_dir(args.path, make_parents=bool(args.parents))
            result = f'created remote directory {args.path}'
        elif args.command == 'plan':
            result = client.get_plan().to_yaml()
        elif args.command == 'pull':
            content = client.pull(args.remote_path, encoding=None).read()
            if args.local_path != '-':
                with open(args.local_path, 'wb') as f:
                    f.write(content)
                result = f'wrote remote file {args.remote_path} to {args.local_path}'
            else:
                sys.stdout.buffer.write(content)
                return
        elif args.command == 'push':
            with open(args.local_path, 'rb') as f:
                client.push(
                    args.remote_path,
                    f,
                    make_dirs=args.dirs,
                    permissions=int(args.mode, 8) if args.mode is not None else None,
                    user=args.user,
                    group=args.group,
                )
            result = f'wrote {args.local_path} to remote file {args.remote_path}'
        elif args.command == 'rm':
            client.remove_path(args.path, recursive=bool(args.recursive))
            result = f'removed remote path {args.path}'
        elif args.command == 'services':
            result = client.get_services(args.service)
        elif args.command == 'start':
            result = client.start_services(args.service)
        elif args.command == 'stop':
            result = client.stop_services(args.service)
        elif args.command == 'system-info':
            result = client.get_system_info()
        elif args.command == 'wait':
            result = client.wait_change(args.change_id, timeout=args.timeout)
        elif args.command == 'warnings':
            result = client.get_warnings(select=pebble.WarningState(args.select))
        else:
            raise AssertionError("shouldn't happen")
    except pebble.APIError as e:
        print(f'APIError: {e.code} {e.status}: {e.message}', file=sys.stderr)
        sys.exit(1)
    except pebble.ConnectionError as e:
        print(f'ConnectionError: cannot connect to socket {socket_path!r}: {e}', file=sys.stderr)
        sys.exit(1)
    except pebble.ChangeError as e:
        print('ChangeError:', e, file=sys.stderr)
        sys.exit(1)

    if isinstance(result, list):
        for x in result:
            print(x)
    elif result is not None:
        print(result)


if __name__ == '__main__':
    main()
