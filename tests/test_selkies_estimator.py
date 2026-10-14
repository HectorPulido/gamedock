import ast
from pathlib import Path
import unittest
from typing import Union
import importlib.util
root = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('estimator_patch', root / 'runtime/patch-selkies-estimator.py')
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)

def estimator(source):
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_estimate_client_fps')
    code = ast.Module(body=[node], type_ignores=[])
    scope = {'Union': Union, 'MAX_UINT16_FRAME_ID':65535, 'FRAME_ID_SUSPICIOUS_GAP_THRESHOLD':32768}
    exec(compile(code, 'native-estimator', 'exec'), scope)
    return scope['_estimate_client_fps']

class Recovery(unittest.TestCase):
    def setUp(self):
        source = (root/'tests/fixtures/selkies-estimator-2.0.0.py').read_text()
        self.original = estimator(source)
        self.fixed = estimator(patch.patch_source(source))
    def test_gate_recovery_does_not_shrink_window_from_throttled_interval(self):
        old, new = {}, {}
        for t, ack, sending in [(0,0,True),(.5,15,True),(.75,16,False),(1,17,False),(1.1,18,True),(1.25,19,True)]:
            old['backpressure_enabled']=new['backpressure_enabled']=sending
            before=self.original(None, old, ack, 30, t)
            after=self.fixed(None, new, ack, 30, t)
        self.assertLess(before,23)
        self.assertEqual(after,30)
    def test_healthy_slow_client_still_scales_window(self):
        state={}
        for n in range(21):
            result=self.fixed(None,state,n*3,30,n*.25)
        self.assertAlmostEqual(result,12,delta=.1)
    def test_wrap_idle_and_suspicious_jump_stay_bounded(self):
        state={}
        self.assertEqual(self.fixed(None,state,65530,30,0),30)
        self.assertEqual(self.fixed(None,state,2,30,.25),30)
        self.assertEqual(self.fixed(None,state,2,30,.5),30)
        self.assertEqual(self.fixed(None,state,50000,30,.75),30)
    def test_live_upgrade_forgets_previously_degraded_estimate(self):
        state={'_fps_sample_acked':10,'_fps_sample_time':0,'_measured_client_fps':6}
        self.assertEqual(self.fixed(None,state,11,30,.3),30)

    def test_patch_rejects_unknown_and_already_patched_contract(self):
        source = (root/'tests/fixtures/selkies-estimator-2.0.0.py').read_text()
        with self.assertRaises(ValueError):
            patch.patch_source(source.replace(patch.OLD, ''))
        with self.assertRaises(ValueError):
            patch.patch_source(patch.patch_source(source))

if __name__ == '__main__':
    unittest.main()
