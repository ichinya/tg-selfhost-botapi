#!/usr/bin/env python3
"""Download by file_id over TLS; never accepts a filesystem path."""
import http.client
import json
import os
import sys
from urllib.parse import urlsplit


def copy_response(response, output):
    lengths = response.headers.get_all('Content-Length', [])
    if (response.status != 200 or len(lengths) != 1
            or not lengths[0].isascii() or not lengths[0].isdecimal()
            or response.getheader('Transfer-Encoding')):
        raise ValueError('invalid download response')
    remaining = int(lengths[0])
    while remaining:
        block = response.read(min(65536, remaining))
        if not block:
            raise ValueError('incomplete download')
        output.write(block)
        remaining -= len(block)


def main():
    if len(sys.argv) != 2: raise ValueError()
    url = urlsplit(os.environ['DOWNLOAD_URL'])
    if url.scheme != 'https' or url.path != '/v1/files/download' or url.query or url.fragment or url.username:
        raise ValueError()
    secret = os.environ.get('DOWNLOAD_AUTH_TOKEN')
    if os.environ.get('DOWNLOAD_AUTH_TOKEN_FILE'):
        if secret: raise ValueError()
        with open(os.environ['DOWNLOAD_AUTH_TOKEN_FILE'], encoding='ascii') as source:
            secret = source.read(257).strip()
    if not secret or len(secret) > 256: raise ValueError()
    connection = http.client.HTTPSConnection(url.hostname, url.port, timeout=30)
    try:
        connection.request('POST', url.path, json.dumps({'file_id': sys.argv[1]}),
                           {'Authorization': 'Bearer ' + secret, 'Content-Type': 'application/json'})
        response = connection.getresponse()
        copy_response(response, sys.stdout.buffer)
    finally: connection.close()


if __name__ == '__main__':
    try: main()
    except (OSError, KeyError, ValueError, http.client.HTTPException):
        print('download unavailable', file=sys.stderr); sys.exit(1)
