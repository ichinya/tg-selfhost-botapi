"""Small amd64 inventory contract for #12; no multi-platform publisher."""
import re


def parse_installed(text):
    packages = []
    for block in text.strip().split('\n\n'):
        fields = {}
        for line in block.splitlines():
            if len(line) < 2 or line[1] != ':':
                raise ValueError('Malformed apk installed database')
            if line[0] in ('P', 'V', 'A', 'o'):
                if line[0] in fields:
                    raise ValueError('Duplicate package identity field')
                fields[line[0]] = line[2:]
        if not all(fields.get(k) for k in ('P', 'V', 'A')) or not re.fullmatch(r'.+-r[0-9]+', fields['V']):
            raise ValueError('Incomplete installed package')
        packages.append({'name': fields['P'], 'version': fields['V'], 'arch': fields['A'],
                         'origin': fields.get('o', fields['P'])})
    if not packages or len({p['name'] for p in packages}) != len(packages):
        raise ValueError('Empty or duplicate installed packages')
    return sorted(packages, key=lambda p: p['name'])


def validate_packages(packages, required, architecture):
    if not required <= {p['name'] for p in packages} or any(p['arch'] not in (architecture, 'noarch') for p in packages):
        raise ValueError('Missing packages or incompatible architecture')
