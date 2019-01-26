#
# This source file is part of the EdgeDB open source project.
#
# Copyright 2016-present MagicStack Inc. and the EdgeDB authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


import getpass
import os
import platform
import typing
import urllib.parse

from . import errors


EDGEDB_PORT = 5656


class ConnectionParameters(typing.NamedTuple):

    user: str
    password: str
    database: str
    connect_timeout: float
    server_settings: typing.Mapping[str, str]


class ClientConfiguration(typing.NamedTuple):

    command_timeout: float


_system = platform.uname().system


def _validate_port_spec(hosts, port):
    if isinstance(port, list):
        # If there is a list of ports, its length must
        # match that of the host list.
        if len(port) != len(hosts):
            raise errors.InterfaceError(
                'could not match {} port numbers to {} hosts'.format(
                    len(port), len(hosts)))
    else:
        port = [port for _ in range(len(hosts))]

    return port


def _parse_hostlist(hostlist, port):
    if ',' in hostlist:
        # A comma-separated list of host addresses.
        hostspecs = hostlist.split(',')
    else:
        hostspecs = [hostlist]

    hosts = []
    hostlist_ports = []

    if not port:
        portspec = os.environ.get('EDGEDB_PORT')
        if portspec:
            if ',' in portspec:
                default_port = [int(p) for p in portspec.split(',')]
            else:
                default_port = int(portspec)
        else:
            default_port = 5432

        default_port = _validate_port_spec(hostspecs, default_port)

    else:
        port = _validate_port_spec(hostspecs, port)

    for i, hostspec in enumerate(hostspecs):
        addr, _, hostspec_port = hostspec.partition(':')
        hosts.append(addr)

        if not port:
            if hostspec_port:
                hostlist_ports.append(int(hostspec_port))
            else:
                hostlist_ports.append(default_port[i])

    if not port:
        port = hostlist_ports

    return hosts, port


def _parse_connect_dsn_and_args(*, dsn, host, port, user,
                                password, database,
                                connect_timeout, server_settings):
    # `auth_hosts` is the version of host information for the purposes
    # of reading the pgpass file.
    auth_hosts = None

    if dsn:
        parsed = urllib.parse.urlparse(dsn)

        if parsed.scheme != 'edgedb':
            raise ValueError(
                f'invalid DSN: scheme is expected to be "edgedb", '
                f'got {parsed.scheme!r}')

        if not host and parsed.netloc:
            if '@' in parsed.netloc:
                auth, _, hostspec = parsed.netloc.partition('@')
            else:
                hostspec = parsed.netloc

            if hostspec:
                host, port = _parse_hostlist(hostspec, port)

        if parsed.path and database is None:
            database = parsed.path
            if database.startswith('/'):
                database = database[1:]

        if parsed.username and user is None:
            user = parsed.username

        if parsed.password and password is None:
            password = parsed.password

        if parsed.query:
            query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
            for key, val in query.items():
                if isinstance(val, list):
                    query[key] = val[-1]

            if 'port' in query:
                val = query.pop('port')
                if not port and val:
                    port = [int(p) for p in val.split(',')]

            if 'host' in query:
                val = query.pop('host')
                if not host and val:
                    host, port = _parse_hostlist(val, port)

            if 'dbname' in query:
                val = query.pop('dbname')
                if database is None:
                    database = val

            if 'database' in query:
                val = query.pop('database')
                if database is None:
                    database = val

            if 'user' in query:
                val = query.pop('user')
                if user is None:
                    user = val

            if 'password' in query:
                val = query.pop('password')
                if password is None:
                    password = val

            if query:
                if server_settings is None:
                    server_settings = query
                else:
                    server_settings = {**query, **server_settings}

    if not host:
        hostspec = os.environ.get('EDGEDB_HOST')
        if hostspec:
            host, port = _parse_hostlist(hostspec, port)

    if not host:
        auth_hosts = ['localhost']

        if _system == 'Windows':
            host = ['localhost']
        else:
            host = ['/run/edgedb', '/var/run/edgedb',
                    '/tmp', '/private/tmp', 'localhost']

    if not isinstance(host, list):
        host = [host]

    if auth_hosts is None:
        auth_hosts = host

    if not port:
        portspec = os.environ.get('EDGEDB_PORT')
        if portspec:
            if ',' in portspec:
                port = [int(p) for p in portspec.split(',')]
            else:
                port = int(portspec)
        else:
            port = EDGEDB_PORT

    elif isinstance(port, (list, tuple)):
        port = [int(p) for p in port]

    else:
        port = int(port)

    port = _validate_port_spec(host, port)

    if user is None:
        user = os.getenv('EDGEDB_USER')
        if not user:
            user = getpass.getuser()

    if password is None:
        password = os.getenv('EDGEDB_PASSWORD')

    if database is None:
        database = os.getenv('EDGEDB_DATABASE')

    if database is None:
        database = user

    if user is None:
        raise errors.InterfaceError(
            'could not determine user name to connect with')

    if database is None:
        raise errors.InterfaceError(
            'could not determine database name to connect to')

    addrs = []
    for h, p in zip(host, port):
        if h.startswith('/'):
            # UNIX socket name
            if '.s.EDGEDB.' not in h:
                h = os.path.join(h, '.s.EDGEDB.{}'.format(p))
            addrs.append(h)
        else:
            # TCP host/port
            addrs.append((h, p))

    if not addrs:
        raise ValueError(
            'could not determine the database address to connect to')

    if server_settings is not None and (
            not isinstance(server_settings, dict) or
            not all(isinstance(k, str) for k in server_settings) or
            not all(isinstance(v, str) for v in server_settings.values())):
        raise ValueError(
            'server_settings is expected to be None or '
            'a Dict[str, str]')

    params = ConnectionParameters(
        user=user,
        password=password,
        database=database,
        connect_timeout=connect_timeout,
        server_settings=server_settings)

    return addrs, params


def parse_connect_arguments(*, dsn, host, port, user, password,
                            database, timeout, command_timeout,
                            server_settings):

    if command_timeout is not None:
        try:
            if isinstance(command_timeout, bool):
                raise ValueError
            command_timeout = float(command_timeout)
            if command_timeout <= 0:
                raise ValueError
        except ValueError:
            raise ValueError(
                'invalid command_timeout value: '
                'expected greater than 0 float (got {!r})'.format(
                    command_timeout)) from None

    addrs, params = _parse_connect_dsn_and_args(
        dsn=dsn, host=host, port=port, user=user,
        password=password,
        database=database, connect_timeout=timeout,
        server_settings=server_settings,
    )

    config = ClientConfiguration(
        command_timeout=command_timeout,
    )

    return addrs, params, config