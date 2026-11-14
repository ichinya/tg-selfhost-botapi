"""Failure/UNKNOWN propagation follows the shipped canonical engine."""
import unittest
from test_migration_engine import EngineTests
from migration_http import Result
from migration_engine import Stop
class ResultContract(EngineTests):
    def test_ambiguous_detach_stops_target_and_resume(self):
        self.api.fault[(self.runtime.source,'logOut')]=Result('unknown','transport_unknown')
        with self.assertRaises(Stop): self.run_plan()
        before=len(self.api.trace)
        with self.assertRaises(Stop): self.run_plan(resume=True)
        self.assertEqual(len(self.api.trace),before)
        self.assertFalse(any(endpoint==self.runtime.target and method=='getMe' for endpoint,method,_ in self.api.trace))
