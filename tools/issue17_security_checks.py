"""Shared synthetic marker scanner; failures never echo the captured content."""
import json
from urllib.parse import quote, unquote


def assert_private_absent(content, markers):
    if isinstance(content, bytes): content=content.decode('utf-8',errors='replace')
    variants=[content]
    for _ in range(3):
        previous=variants[-1]
        try:
            decoded=unquote(previous)
            # JSON escape forms may occur inside malformed JSON or log wrappers.
            import re
            decoded=re.sub(r'\\u([0-9a-fA-F]{4})',lambda m:chr(int(m[1],16)),decoded)
            decoded=decoded.replace('\\/','/')
        except (ValueError,UnicodeError): raise AssertionError('privacy_scan_failed') from None
        variants.append(decoded)
    for marker in markers:
        if not isinstance(marker,str) or not marker: raise ValueError('invalid synthetic marker')
        forms=(marker,quote(marker,safe=''),quote(quote(marker,safe=''),safe=''),json.dumps(marker)[1:-1])
        if any(form in value for form in forms for value in variants):
            raise AssertionError('private_marker_detected')
    return len(variants)
