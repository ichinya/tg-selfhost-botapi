import copy, unittest
from multiarch_publish import validate_pair
class PairTests(unittest.TestCase):
    def test_exact_pair_and_rejections(self):
        pair=[dict(architecture=arch,sha='a'*40,run_id='1',inputs={'source':'s','build_key':arch,'platform':'linux/'+arch},components={role:'ghcr.io/example/api@sha256:'+'a'*64 for role in ('botapi','observer','downloads')},native=True,qualified=True) for arch in ('amd64','arm64')]
        validate_pair(pair,'a'*40,'1')
        for change in ('sha','native','inputs','components'):
            bad=copy.deepcopy(pair)
            bad[1][change]={'sha':'b'*40,'native':False,'inputs':{'source':'other'},'components':{}}[change]
            with self.subTest(change=change),self.assertRaises(ValueError): validate_pair(bad,'a'*40,'1')
