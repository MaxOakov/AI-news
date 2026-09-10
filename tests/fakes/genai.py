"""A minimal stand-in for google.genai.Client, shaped just enough to satisfy
NewsGenerator._generate_content's `client.aio.models.generate_content(...)`
call and its `.candidates[0].content.parts[0].text` response shape.
"""
from types import SimpleNamespace


class FakeGenAIClient:
    def __init__(self, response_text: str = "Rewritten text"):
        self.calls: list[tuple] = []
        self._response_text = response_text
        self._fail_times = 0
        self._exception_factory = lambda: RuntimeError("simulated Gemini failure")
        self._empty_times = 0
        self.aio = SimpleNamespace(models=_FakeModels(self))

    def set_response(self, text: str):
        self._response_text = text

    def fail_times(self, n: int, exc: Exception | None = None):
        """Make the next `n` calls raise before any later call succeeds."""
        self._fail_times = n
        if exc is not None:
            self._exception_factory = lambda: exc

    def return_empty_candidates(self, n: int):
        """Make the next `n` calls (after any fail_times) return no candidates."""
        self._empty_times = n


class _FakeModels:
    def __init__(self, client: FakeGenAIClient):
        self._client = client

    async def generate_content(self, model, contents):
        self._client.calls.append((model, contents))
        call_index = len(self._client.calls)

        if call_index <= self._client._fail_times:
            raise self._client._exception_factory()

        if call_index <= self._client._fail_times + self._client._empty_times:
            return SimpleNamespace(candidates=[])

        part = SimpleNamespace(text=self._client._response_text)
        content = SimpleNamespace(parts=[part])
        candidate = SimpleNamespace(content=content)
        return SimpleNamespace(candidates=[candidate])
