import unittest
from doctor_checks import qualification_metadata_checks,report
class MetadataTests(unittest.TestCase):
    def test_missing_metadata_cannot_claim_native_or_package_qualification(self):
        checks=qualification_metadata_checks({},'target.botapi',apk=True)
        self.assertTrue(all(row['status']=='unknown' for row in checks))
        self.assertTrue(all(not row['required'] for row in checks))
    def test_labels_do_not_qualify_native_runtime(self):
        image=dict(Os='linux',Architecture='arm64',Config={'Labels':{'org.opencontainers.image.revision':'a'*40,'io.tg-selfhost.apk-refresh':'v1-2026-11-15-g0'}})
        checks=qualification_metadata_checks(image,'target.botapi',apk=True)
        self.assertEqual(checks[0]['status'],'unknown')
        self.assertEqual(checks[1]['status'],'pass')
        image['Architecture']='mips64'
        self.assertTrue(any(row['required'] and row['status']=='fail' for row in qualification_metadata_checks(image,'target.botapi')))
