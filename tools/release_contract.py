"""Public release records. Validation is structural, never proof of a live gate."""
import argparse
import hashlib
import json
from pathlib import Path
import re

QUALIFICATION_VERSION = 1
GATES = ("unit", "static", "image", "runtime_ua", "restore", "apk_policy")
SHA = r"[0-9a-f]{40}"
DIGEST = r"sha256:[0-9a-f]{64}"


def match(value, pattern, name):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("Invalid " + name)


def validate_checks(checks, approved=False):
    if not isinstance(checks, dict) or set(checks) != set(GATES):
        raise ValueError('Missing qualification gates')
    for gate in checks.values():
        if not isinstance(gate, dict) or set(gate) != {'status', 'evidence_sha256'}:
            raise ValueError('Invalid gate')
        if gate['status'] not in ('PASS', 'FAIL', 'UNKNOWN', 'NOTRUN'):
            raise ValueError('Invalid gate status')
        if gate['status'] == 'PASS':
            match(gate['evidence_sha256'], r'[0-9a-f]{64}', 'gate evidence')
        elif gate['evidence_sha256'] is not None:
            raise ValueError('Unexecuted gate must not claim evidence')
        if approved and gate['status'] != 'PASS':
            raise ValueError('Approval requires every offline qualification gate')


def validate_inputs(record):
    from image_inputs import validate_lock, validate_policy
    if not isinstance(record, dict) or set(record) not in ({"schema", "inputs", "selected_release", "apk_policy", "discovery"},
                                                 {"schema", "inputs", "selected_release", "apk_policy", "discovery", "recipe_sha256"}):
        raise ValueError("Unexpected input record fields")
    if 'recipe_sha256' in record:
        hashes = record['recipe_sha256']
        if not isinstance(hashes, dict) or not hashes:
            raise ValueError('Invalid recipe digests')
        for path, value in hashes.items():
            if not isinstance(path, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', path) or '..' in path.split('/'):
                raise ValueError('Invalid recipe path')
            match(value, r'[0-9a-f]{64}', 'recipe digest')
    inputs = validate_lock(record)
    if set(inputs) != {'bot_api_revision', 'wrapper_revision', 'alpine_image', 'platform', 'bot_api_version',
                       'apk_policy_version', 'apk_refresh_window', 'apk_refresh_generation', 'apk_refresh_id', 'submodules', 'observer_base', 'python_image'}:
        raise ValueError('Saved inputs contain derived or private fields')
    policy = record["apk_policy"]
    validate_policy(policy)
    if (not isinstance(policy, dict) or type(policy.get('policy_version')) is not int
            or type(policy.get('generation')) is not int
            or policy.get('policy_version') != inputs['apk_policy_version']
            or policy.get('generation') != inputs['apk_refresh_generation']
            or policy.get('refresh_window') != 'utc-day' or 'status' in policy):
        raise ValueError("Saved apk policy differs from build inputs")
    if record["selected_release"] is not None:
        raise ValueError("Deployment selection belongs in image-release.lock.json")
    discovery = record['discovery']
    if (not isinstance(discovery, dict) or set(discovery) != {
            'source_repository', 'observed_date', 'alpine_index_digest', 'alpine_amd64_digest',
            'nginx_candidate_image', 'nginx_version', 'nginx_amd64_digest', 'qualification'}):
        raise ValueError('Invalid discovery record')
    if discovery['source_repository'] != 'https://github.com/tdlib/telegram-bot-api':
        raise ValueError('Unexpected source repository')
    match(discovery['observed_date'], r'[0-9]{4}-[0-9]{2}-[0-9]{2}', 'observation date')
    for name in ('alpine_index_digest', 'alpine_amd64_digest', 'nginx_amd64_digest'):
        match(discovery[name], DIGEST, name)
    if not inputs['alpine_image'].endswith('@' + discovery['alpine_index_digest']):
        raise ValueError('Base index differs from inputs')
    match(discovery['nginx_candidate_image'], r'nginx:[A-Za-z0-9._-]+@' + DIGEST, 'nginx candidate')
    match(discovery['nginx_version'], r'[0-9]+\.[0-9]+\.[0-9]+', 'nginx version')
    if discovery['qualification'] != 'NOTRUN':
        raise ValueError('Discovery does not qualify a deployment')
    return inputs


def validate_receipt(receipt, expected, approved=False):
    required = {"schema", "qualification_version", "build_key", "platform", "server_revision",
                "server_version", "tdlib_revision", "wrapper_revision", "config_id", "index_digest",
                "platform_digest", "binary_sha256", "recipe_sha256", "inventories_sha256",
                "patch_sha256", "entrypoint_sha256", "checks", "provenance", "gateway",
                "qualification_key", "components"}
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise ValueError("Unexpected receipt fields")
    if type(receipt["schema"]) is not int or receipt["schema"] != 1:
        raise ValueError("Unsupported receipt schema")
    if type(receipt["qualification_version"]) is not int or receipt["qualification_version"] != QUALIFICATION_VERSION:
        raise ValueError("Unsupported qualification version")
    for field in ("server_revision", "tdlib_revision", "wrapper_revision"):
        match(receipt[field], SHA, field)
    for field in ("config_id", "index_digest", "platform_digest"):
        match(receipt[field], DIGEST, field)
    for field in ("binary_sha256", "patch_sha256", "entrypoint_sha256"):
        match(receipt[field], r"[0-9a-f]{64}", field)
    match(receipt["build_key"], r"[0-9a-f]{32}", "build key")
    match(receipt['qualification_key'], r'[0-9a-f]{32}', 'qualification key')
    if receipt['qualification_key'] != expected['qualification_key']:
        raise ValueError('Qualification recipe differs from saved inputs')
    components = receipt['components']
    if not isinstance(components, dict) or set(components) != {'botapi', 'observer', 'downloads', 'sender'}:
        raise ValueError('Incomplete qualified component bundle')
    for name, component in components.items():
        if not isinstance(component, dict) or set(component) != {'image', 'config_id', 'rootfs_sha256'}:
            raise ValueError('Invalid component: ' + name)
        match(component['image'], r'[^\s@]+@' + DIGEST, 'component reference')
        match(component['config_id'], DIGEST, 'component config')
        match(component['rootfs_sha256'], r'[0-9a-f]{64}', 'component rootfs')
    if (components['botapi']['config_id'] != receipt['config_id']
            or not components['botapi']['image'].endswith('@' + receipt['index_digest'])):
        raise ValueError('Bot API component differs from receipt identity')
    for name in ("recipe_sha256", "inventories_sha256"):
        values = receipt[name]
        if not isinstance(values, dict) or not values:
            raise ValueError("Missing " + name)
        for path, value in values.items():
            if not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", path) or ".." in path.split("/"):
                raise ValueError("Invalid evidence path")
            match(value, r"[0-9a-f]{64}", name)
    if receipt["platform"] != "linux/amd64" or receipt["server_version"] != expected["bot_api_version"]:
        raise ValueError("Platform or source version mismatch")
    if (receipt["server_revision"] != expected["bot_api_revision"]
            or receipt['wrapper_revision'] != expected['wrapper_revision']
            or receipt["tdlib_revision"] != expected["submodules"]["td"]
            or receipt["build_key"] != expected["build_key"]):
        raise ValueError("Receipt differs from saved inputs")
    checks = receipt["checks"]
    validate_checks(checks, approved)
    if receipt["provenance"] not in ("ci", "manual-live"):
        raise ValueError("Invalid provenance")
    gateway = receipt['gateway']
    if (not isinstance(gateway, dict) or set(gateway) != {'image', 'config_id', 'platform_digest', 'version'}
            or gateway['image'] != expected.get('nginx_image')
            or gateway['platform_digest'] != expected.get('nginx_platform_digest')
            or gateway['version'] != expected.get('nginx_version')):
        raise ValueError('Gateway differs from saved candidate')
    match(gateway['config_id'], DIGEST, 'gateway config')
    match(gateway['version'], r'[0-9]+\.[0-9]+\.[0-9]+', 'actual nginx version')
    if approved and any(g['status'] != 'PASS' for g in checks.values()):
        raise ValueError('Approval requires every offline qualification gate')
    return receipt


def validate_selected(record, inputs, receipt=None):
    if not isinstance(record, dict) or set(record) != {"schema", "selected_release"} or type(record["schema"]) is not int or record["schema"] != 1:
        raise ValueError("Invalid selection schema")
    selected = record["selected_release"]
    if selected is None:
        return None
    if not isinstance(selected, dict) or set(selected) != {"botapi_image", "observer_image", "downloads_image", "nginx_image", "receipt_sha256"}:
        raise ValueError("Invalid selection fields")
    for name in ("botapi_image", "observer_image", "downloads_image", "nginx_image"):
        match(selected[name], r"[^\s@]+@" + DIGEST, name)
    match(selected["receipt_sha256"], r"[0-9a-f]{64}", "receipt hash")
    if receipt is None:
        raise ValueError("Selection requires the actual receipt bytes")
    if hashlib.sha256(receipt).hexdigest() != selected["receipt_sha256"]:
        raise ValueError("Receipt hash mismatch")
    verified = validate_receipt(json.loads(receipt), inputs, approved=True)
    if not selected["botapi_image"].endswith("@" + verified["index_digest"]):
        raise ValueError("Selected digest differs from receipt")
    if selected['nginx_image'] != verified['gateway']['image']:
        raise ValueError('Selected gateway differs from receipt')
    for name in ('botapi', 'observer', 'downloads'):
        if selected[name + '_image'] != verified['components'][name]['image']:
            raise ValueError('Selection differs from qualified component bundle')
    return selected


def select_release(inputs, receipt_bytes, botapi_image):
    """Explicit selection from a trusted qualified receipt; no network or deployment."""
    verified = validate_receipt(json.loads(receipt_bytes), inputs, approved=True)
    from image_inputs import recipe_files
    recipe = {path: hashlib.sha256(raw).hexdigest() for path, raw in recipe_files().items()}
    if verified['recipe_sha256'] != recipe:
        raise ValueError('Receipt recipe differs from the current candidate')
    record = {'schema': 1, 'selected_release': {
        'botapi_image': botapi_image, 'nginx_image': verified['gateway']['image'],
        'observer_image': verified['components']['observer']['image'],
        'downloads_image': verified['components']['downloads']['image'],
        'receipt_sha256': hashlib.sha256(receipt_bytes).hexdigest()}}
    selected = validate_selected(record, inputs, receipt_bytes)
    env = ''.join(key.upper() + '=' + selected[key] + '\n' for key in ('botapi_image', 'observer_image', 'downloads_image'))
    env += 'GATEWAY_IMAGE=' + selected['nginx_image'] + '\n'
    return record, env


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--inputs-file', type=Path, help='CI input snapshot from release evidence')
    parser.add_argument('--select-receipt', type=Path, help='Explicitly select an already qualified public receipt')
    parser.add_argument('--botapi-image', help='Qualified immutable tag@digest from that receipt')
    args = parser.parse_args()
    from image_inputs import resolve
    input_path = args.inputs_file or args.root / 'image-inputs.lock.json'
    validate_inputs(json.loads(input_path.read_text(encoding="utf-8")))
    inputs = resolve(inputs_file=input_path)
    if args.select_receipt:
        if not args.botapi_image:
            parser.error('--botapi-image is required for explicit selection')
        raw = args.select_receipt.read_bytes()
        record, env = select_release(inputs, raw, args.botapi_image)
        # Validate completely before changing public projections. These writes are
        # separate files: review them together before committing a selection.
        receipt_path = args.root / 'releases/receipts' / (hashlib.sha256(raw).hexdigest() + '.json')
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        if receipt_path.exists() and receipt_path.read_bytes() != raw:
            raise ValueError('Receipt content differs from its archive hash')
        receipt_path.write_bytes(raw)
        (args.root / 'image-release.lock.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf8', newline='\n')
        (args.root / 'selected.env').write_text(env, encoding='utf8', newline='\n')
        print('Qualified release selected; deployment was not changed')
    else:
        selected_path = args.root / 'image-release.lock.json'
        selected = json.loads(selected_path.read_text(encoding='utf8'))
        receipt_bytes = None
        if selected.get('selected_release'):
            public = selected['selected_release']
            if not isinstance(public, dict):
                raise ValueError('Invalid selection')
            match(public.get('receipt_sha256'), r'[0-9a-f]{64}', 'receipt hash')
            receipt_bytes = (args.root / 'releases/receipts' / (public['receipt_sha256'] + '.json')).read_bytes()
        validate_selected(selected, inputs, receipt_bytes)
        print('Selected bundle receipt validated' if receipt_bytes else 'Saved inputs valid; no approved deployment selected')
