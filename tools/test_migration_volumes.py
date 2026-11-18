import copy
from pathlib import Path
import unittest
from check_migration_volumes import checked_resource,checked_mounts,GateError,LABEL,DATA,TEMP,FAKE


class VolumeGuardTests(unittest.TestCase):
    def test_exact_id_project_and_run_required(self):
        info={'Id':'container-id','Config':{'Labels':{LABEL:'run','com.docker.compose.project':'project'}}}
        checked_resource(info,'container','container-id','run','project')
        for identity,run,project in [('other','run','project'),('container-id','other','project'),('container-id','run','other')]:
            with self.assertRaises(GateError):
                checked_resource(info,'container',identity,run,project)

    def test_mount_allowlist_rejects_production_paths_and_extras(self):
        fake=str(Path(__file__).resolve())
        volumes={DATA:'fixture_data',TEMP:'fixture_temp'}
        info={'Mounts':[{'Destination':d,'Type':'volume','Name':n,'RW':True} for d,n in volumes.items()]+[
                       {'Destination':FAKE,'Type':'bind','Source':fake,'RW':False}]}
        checked_mounts(info,volumes,fake)
        bad=copy.deepcopy(info)
        bad['Mounts'][0].update(Type='bind',Source='/production/data')
        with self.assertRaises(GateError):
            checked_mounts(bad,volumes,fake)
        bad=copy.deepcopy(info)
        bad['Mounts'].append({'Destination':'/unexpected'})
        with self.assertRaises(GateError):
            checked_mounts(bad,volumes,fake)

    def test_foreign_canary_rejected(self):
        info={'Name':'canary','Labels':{LABEL:'another-run','com.docker.compose.project':'project'}}
        with self.assertRaises(GateError):
            checked_resource(info,'volume','canary','run','project')
