import io, tarfile, unittest
from state_lifecycle import archive_manifest,validate_shutdown
class LifecycleTests(unittest.TestCase):
    def test_manifest_content_ownership_and_links(self):
        def archive(link=False):
            raw=io.BytesIO()
            with tarfile.open(fileobj=raw,mode='w') as out:
                item=tarfile.TarInfo('bot/state'); item.uid=1000; item.gid=1000
                if link: item.type=tarfile.SYMTYPE; item.linkname='/private'
                else: item.size=3
                out.addfile(item,None if link else io.BytesIO(b'abc'))
            return raw.getvalue()
        self.assertEqual(archive_manifest(archive())['bot/state'][1:3],(1000,1000))
        with self.assertRaises(ValueError): archive_manifest(archive(True))
    def test_shutdown_requires_observed_term_and_success(self):
        events=[dict(Action='kill',Actor={'Attributes':{'signal':'15'}}),dict(Action='die',Actor={'Attributes':{'exitCode':'0'}})]
        state=dict(Running=False,OOMKilled=False,ExitCode=0)
        validate_shutdown(events,state)
        for bad in ([],events+[dict(Action='oom')],[dict(Action='kill',Actor={'Attributes':{'signal':'9'}})]):
            with self.assertRaises(ValueError): validate_shutdown(bad,state)
