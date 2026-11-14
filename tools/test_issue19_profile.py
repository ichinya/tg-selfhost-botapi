import unittest
from migration_contract import validate_profile

class ProfileTests(unittest.TestCase):
    def profile(self):
        return dict(mode='full',url='https://receiver.example/hook',secret_token=None,
                    certificate_pem=None,ip_address=None,allowed_updates=[],max_connections=40)
    def test_full_requires_every_explicit_choice(self):
        profile=self.profile()
        validate_profile(profile,'preserve')
        for key in ('secret_token','certificate_pem','ip_address','allowed_updates','max_connections'):
            bad={k:v for k,v in profile.items() if k != key}
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_profile(bad,'preserve')
    def test_unknown_values_do_not_become_absence(self):
        for key in ('secret_token','certificate_pem','ip_address'):
            profile=self.profile(); profile[key]={'state':'unknown'}
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_profile(profile,'set')
