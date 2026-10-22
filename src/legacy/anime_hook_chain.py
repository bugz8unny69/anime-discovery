"""Small, deterministic, synchronous hook pipeline.

Hooks run in registration order. A hook must return CONTINUE, STOP, RETRY,
or REVIEW. Hooks cannot silently return None or launch background work.
"""
from dataclasses import dataclass

OUTCOMES = frozenset(("CONTINUE", "STOP", "RETRY", "REVIEW"))

@dataclass(frozen=True)
class Hook:
    name: str
    callback: object

class HookRegistry:
    def __init__(self):
        self._stages = {}

    def register(self, stage, name, callback):
        if not isinstance(stage, str) or not stage or not isinstance(name, str) or not name:
            raise ValueError("Hook stage and name required")
        if not callable(callback):
            raise ValueError("Hook must be callable")
        hooks = self._stages.setdefault(stage, [])
        if any(h.name == name for h in hooks):
            raise ValueError("Duplicate hook name")
        hooks.append(Hook(name, callback))

    def unregister(self, stage, name):
        hooks = self._stages.get(stage, [])
        matched = [hook for hook in hooks if hook.name == name]
        if not matched:
            raise ValueError("Hook not registered")
        hooks.remove(matched[0])

    def run(self, stage, context, *, on_event=None):
        for hook in tuple(self._stages.get(stage, ())):
            if on_event is not None:
                on_event("HOOK_STARTED", stage, hook.name, None)
            try:
                outcome = hook.callback(context)
                if outcome not in OUTCOMES:
                    raise ValueError("Invalid hook outcome")
            except Exception:
                if on_event is not None:
                    on_event("HOOK_FAILED", stage, hook.name, "RETRY")
                raise
            if on_event is not None:
                on_event("HOOK_FINISHED", stage, hook.name, outcome)
            if outcome != "CONTINUE":
                return outcome
        return "CONTINUE"
