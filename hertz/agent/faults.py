import time


class DownClient:
    def converse(self, **kw):
        raise ConnectionError("injected fault: Bedrock endpoint unreachable")


class TextOnlyClient:
    def converse(self, **kw):
        return {"output": {"message": {"role": "assistant", "content": [{"text": "I think there is a drone."}]}},
                "usage": {"inputTokens": 0, "outputTokens": 0}}


class ScriptedClient:
    def __init__(self, uses):
        self.uses, self.i = list(uses), 0

    def converse(self, **kw):
        name, args = self.uses[min(self.i, len(self.uses) - 1)]
        self.i += 1
        return {"output": {"message": {"role": "assistant", "content": [
            {"text": f"injected step {self.i}"}, {"toolUse": {"toolUseId": f"fault-{self.i}", "name": name, "input": args}}]}},
            "usage": {"inputTokens": 0, "outputTokens": 0}}


def slow(fn, delay_s, times=1):
    state = {"n": 0}

    def wrap(*a, **k):
        if state["n"] < times:
            state["n"] += 1
            time.sleep(delay_s)
        return fn(*a, **k)
    return wrap
