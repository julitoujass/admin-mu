"""Recording stand-in for the Supabase client used by service tests."""

from types import SimpleNamespace


class FakeQuery:
    """Records every chained builder call and answers `execute()` from the owner's queue."""

    def __init__(self, owner, kind, name, params=None):
        self._owner = owner
        self.kind = kind
        self.name = name
        self.params = params
        self.calls = []

    def __getattr__(self, method):
        def record(*args, **kwargs):
            self.calls.append((method, args, kwargs))
            return self

        return record

    def args_of(self, method):
        """Positional args of every call to `method`, in order."""
        return [args for name, args, _ in self.calls if name == method]

    def execute(self):
        self._owner.executed.append(self)
        return SimpleNamespace(data=self._owner.next_response())


class FakeSupabase:
    """`FakeSupabase(resp1, resp2, ...)`: the n-th executed query receives the n-th response.

    A response that is an Exception instance is raised instead. Once the queue is
    exhausted every query gets an empty list.
    """

    def __init__(self, *responses):
        self._responses = list(responses)
        self.queries = []
        self.executed = []

    def next_response(self):
        if not self._responses:
            return []
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def table(self, name):
        query = FakeQuery(self, "table", name)
        self.queries.append(query)
        return query

    def rpc(self, name, params=None):
        query = FakeQuery(self, "rpc", name, params)
        self.queries.append(query)
        return query

    def rpc_calls(self, name=None):
        return [q for q in self.queries if q.kind == "rpc" and (name is None or q.name == name)]

    def table_calls(self, name=None):
        return [q for q in self.queries if q.kind == "table" and (name is None or q.name == name)]
