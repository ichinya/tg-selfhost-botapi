import unittest
from observability.stats import parse, HEADER


def sample(pending=None):
    return (HEADER + b'\nuptime\t1.5\nbot_count\t1\nactive_bot_count\t1\n\n'
            b'id\t123\nuptime\t1\ntoken\t123456:FAKE_SECRET\nusername\tprivate\nhead_update_id\t2\n'
            + (b'pending_update_count\t' + pending + b'\n' if pending is not None else b''))


class StatsTests(unittest.TestCase):
    def test_missing_is_not_zero_and_secret_is_dropped(self):
        actual = parse(sample())
        self.assertIsNone(actual['queue']['pending_lower_bound'])
        self.assertEqual(parse(sample(b'0'))['queue']['pending_lower_bound'], 0)
        self.assertNotIn('FAKE_SECRET', repr(actual))
        self.assertEqual(actual['queue']['coverage'], 'sampled')

    def test_invalid_and_truncated_fail_closed(self):
        for body in [b'Closing\n', sample()[:-1], sample(b'-1'), sample(b'true'), sample(b'99999999999999999999'),
                     sample() + b'\n', sample() + b'pending_update_count\t1\npending_update_count\t2\n',
                     sample().replace(b'uptime\t1.5', b'uptime\t1.5\nuptime\t2')]:
            with self.subTest(length=len(body)), self.assertRaises(ValueError): parse(body)

    def test_unknown_sensitive_fields_and_client_limit(self):
        actual = parse(sample(b'3') + b'new_url\thttps://private.invalid/SECRET\n')
        self.assertEqual(actual['queue']['pending_lower_bound'], 3)
        self.assertNotIn('SECRET', repr(actual))
        block = sample().split(b'\n\n')[1]
        with self.assertRaises(ValueError): parse(sample().split(b'\n\n')[0] + b'\n\n' + b'\n'.join([block] * 51))
