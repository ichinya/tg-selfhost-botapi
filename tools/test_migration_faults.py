"""Real loopback loss matrix: UNKNOWN never silently authorizes a replay."""
import unittest
from migration_engine import Engine, Runtime, Stop
from migration_http import Client
from migration_mock import Bot, TOKEN, deployment
from migration_probe import Readiness
from migration_store import Journal
from test_migration_state_privacy import MemoryStore


class FaultMatrixTests(unittest.TestCase):
    def test_response_loss_before_and_after_every_mutation(self):
        for method,side,direction in [('deleteWebhook','source','cloud_to_local'),
                                      ('logOut','source','cloud_to_local'),
                                      ('close','source','local_to_local'),
                                      ('deleteWebhook','target','cloud_to_local')]:
            for fault in ('lost_unapplied','lost_applied'):
                with self.subTest(method=method,side=side,fault=fault):
                    trace=[]
                    source,target=Bot('source',trace),Bot('target',trace)
                    try:
                        j=Journal(MemoryStore()); j.bot='123'
                        client=Client(fixture=True,connect_timeout=.2,read_timeout=.2,total_timeout=.5)
                        runtime=Runtime(source.endpoint,target.endpoint,TOKEN,{'mode':'polling'},'polling',
                                        drop=side=='target',fixture=True,direction=direction)
                        engine=Engine(j,client,Readiness(client,lambda:deployment(target.endpoint),j.key),runtime)
                        state=engine.prepare('fault',quiescence='fixture')
                        bot=source if side=='source' else target
                        bot.faults[method]=fault
                        args=dict(confirm_digest=state['digest'],quiescence='fixture',endpoint_change='fixture',application_start='fixture',resume=True)
                        with self.assertRaises(Stop): engine.run(state,**args)
                        step='source_delete' if side=='source' and method=='deleteWebhook' else 'source_close' if method=='close' else 'source_logout' if method=='logOut' else 'target_configure'
                        self.assertEqual(j.outcome(state,step),'unknown')
                        original=bot.effects[method]
                        trace.clear()
                        try: engine.run(state,**args)
                        except Stop: pass
                        self.assertEqual(bot.effects[method],original)
                        if step in ('source_logout','source_close'):
                            self.assertEqual(trace,[])
                        if step=='target_configure': self.assertEqual(target.effects['drop'],int(fault=='lost_applied'))
                    finally:
                        target.close(); source.close()
