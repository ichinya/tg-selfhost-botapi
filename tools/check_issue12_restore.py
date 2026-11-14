"""Validate cold backup manifests; no authority to stop or restore a live service."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from smoke_image import archive_manifest, validate_shutdown


def validate_backup(record, archives):
    required = {'schema', 'snapshot_id', 'stopped_cleanly', 'release_receipt_sha256', 'config_sha256', 'layout', 'members'}
    if not isinstance(record, dict) or set(record) != required or type(record['schema']) is not int or record['schema'] != 1:
        raise ValueError('Unknown backup manifest')
    if (record['stopped_cleanly'] is not True or not isinstance(record['snapshot_id'], str)
            or not re.fullmatch(r'[a-f0-9]{32}', record['snapshot_id'])):
        raise ValueError('Backup requires an observed clean stop and one snapshot identity')
    for name in ('release_receipt_sha256', 'config_sha256'):
        if not isinstance(record[name], str) or not re.fullmatch(r'[a-f0-9]{64}', record[name]):
            raise ValueError('Missing saved release/config identity')
    if record['layout'] not in ('base', 'nonroot-split'):
        raise ValueError('Unsupported storage layout')
    members = record['members']
    names = {'state', 'private'} | ({'media'} if record['layout'] == 'nonroot-split' else set())
    if not isinstance(members, dict) or set(members) != names or set(archives) != names:
        raise ValueError('Incomplete or mixed storage snapshot')
    manifest = {}
    mappings = set()
    for name in sorted(names):
        entry = members[name]
        if not isinstance(entry, dict) or set(entry) != {'snapshot_id', 'sha256', 'storage_mapping'}:
            raise ValueError('Invalid archive member metadata')
        if entry['snapshot_id'] != record['snapshot_id'] or entry['sha256'] != hashlib.sha256(archives[name]).hexdigest():
            raise ValueError('Mixed or corrupt archive')
        if not isinstance(entry['storage_mapping'], str) or not entry['storage_mapping']:
            raise ValueError('Missing private storage mapping')
        if entry['storage_mapping'] in mappings:
            raise ValueError('Aliased private storage mapping')
        mappings.add(entry['storage_mapping'])
        tree = archive_manifest(archives[name])
        if not tree:
            raise ValueError('Empty backup archive')
        manifest[name] = tree
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--archive-directory', type=Path, required=True)
    args = p.parse_args()
    record = json.loads(args.manifest.read_text(encoding='utf8'))
    if not isinstance(record.get('members'), dict) or not set(record['members']) <= {'state', 'private', 'media'}:
        raise ValueError('Invalid private archive names')
    archives = {name: (args.archive_directory / (name + '.tar')).read_bytes() for name in record['members']}
    validate_backup(record, archives)
    print('Backup manifest/content/ownership structure PASS; live restore NOTRUN')


if __name__ == '__main__':
    main()
