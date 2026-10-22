import unittest
from anime_hook_chain import HookRegistry

class HookTests(unittest.TestCase):
    def test_order_and_context(self):
        registry=HookRegistry()
        registry.register("identity","first",lambda ctx:ctx.append("first") or "CONTINUE")
        registry.register("identity","second",lambda ctx:ctx.append("second") or "STOP")
        registry.register("identity","third",lambda ctx:ctx.append("third") or "CONTINUE")
        observed=[]
        events=[]
        self.assertEqual(registry.run("identity",observed,on_event=lambda *args:events.append(args)),"STOP")
        self.assertEqual(observed,["first","second"])
        self.assertEqual([e[0] for e in events],["HOOK_STARTED","HOOK_FINISHED"]*2)

    def test_unregister_and_duplicate(self):
        registry=HookRegistry()
        registry.register("identity","one",lambda ctx:"CONTINUE")
        with self.assertRaises(ValueError):
            registry.register("identity","one",lambda ctx:"CONTINUE")
        registry.unregister("identity","one")
        self.assertEqual(registry.run("identity",{}),"CONTINUE")

    def test_failure_stops(self):
        registry=HookRegistry()
        registry.register("identity","one",lambda ctx:None)
        with self.assertRaises(ValueError):
            registry.run("identity",{})
