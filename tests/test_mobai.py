import unittest
from jev_ios.mobai import _parse_tree, MobAIDevice
from jev_ios.suite import WorkerSpec


class FakeClient:
    def __init__(self):
        self.calls=[]
        self.tree='[0] Button "Settings" #settings [enabled]\n[1] Input "Email" #email [enabled]'
    def request(self,method,path,body=None,lease=None):
        self.calls.append((method,path,body,lease))
        if path=="/devices/claim":
            return {"deviceId":"dev","leaseToken":"lease","expiresAt":"later"}
        if path=="/devices/release":
            return {}
        if path.endswith("/bridge/start"):
            return {}
        if path.endswith("/dsl/execute"):
            return {"success":True,"step_results":[{"success":True,"result":{"observations":{"native":{"ui_tree":self.tree}}}}]}
        return []


class MobAITests(unittest.TestCase):
    def test_compact_tree_maps_to_semantic_targets(self):
        snap=_parse_tree('[0] Button "Settings" #settings [enabled]\n[1] Input "Email" #email [enabled]')
        self.assertEqual(snap.labels,["Settings","Email"])
        self.assertEqual(len(snap.targets("tap")),2)
        self.assertEqual(len(snap.targets("type")),1)
        self.assertEqual(snap.elements[0]["predicate"],{"accessibility_id":"settings"})

    def test_device_claims_starts_bridge_and_releases(self):
        dev=MobAIDevice("dev","com.example.app")
        fake=FakeClient(); dev.client=fake
        with dev:
            self.assertEqual(dev.lease,"lease")
        paths=[c[1] for c in fake.calls]
        self.assertIn("/devices/claim",paths)
        self.assertIn("/devices/dev/bridge/start",paths)
        self.assertIn("/devices/release",paths)

    def test_execute_uses_predicate_not_coordinates(self):
        dev=MobAIDevice("dev","com.example.app"); dev.lease="lease"
        fake=FakeClient(); dev.client=fake
        snap=dev.observe()
        target=next(iter(snap.targets("tap")))
        dev.execute(snap,{"operation":"TAP","target":target},{})
        dsl=[c for c in fake.calls if c[1].endswith("/dsl/execute")]
        action=dsl[-2][2]["steps"][0]
        self.assertEqual(action["action"],"tap")
        self.assertEqual(action["predicate"],{"accessibility_id":"settings"})
        self.assertNotIn("coords",action)

    def test_pool_worker_accepts_mobai_ids(self):
        w=WorkerSpec("cloud-iphone","provider-device-123",transport="mobai",mobai_url="https://host.example/api/v1")
        self.assertEqual(w.transport,"mobai")
        with self.assertRaises(ValueError):
            WorkerSpec("bad","not-a-uuid")


if __name__=="__main__":
    unittest.main()
