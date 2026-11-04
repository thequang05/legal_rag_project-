import json

import httpx
import openai
import pytest

from backend.generation import AnswerGenerator


def test_openai_request_and_structured_response(monkeypatch):
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        result = {"claims": [{"citation_id":"1", "quote":"Evidence"}], "insufficient_evidence":False}
        return httpx.Response(200, json={"id": "chatcmpl-test", "object": "chat.completion", "created": 0,
            "model": "gpt-4o-mini", "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(result)}, "finish_reason": "stop"}]})
    monkeypatch.setattr("backend.generation.OpenAI", lambda **kwargs: openai.OpenAI(
        **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler))))
    result = AnswerGenerator("not-a-real-key", "gpt-4o-mini").answer("Question?", [
        {"citation_id":"1", "text":"Evidence", "document_code":"TEST", "version":"1", "page":1, "article":"", "clause":"", "point":""}])
    assert result["claims"][0]["citation_id"] == "1"
    assert captured[0]["response_format"]["json_schema"]["strict"] is True
    assert captured[0]["messages"][0]["role"] == "system"
    assert json.loads(captured[0]["messages"][1]["content"])["evidence"][0]["id"] == "1"


def test_missing_key_is_explicit():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        AnswerGenerator("", "gpt-4o-mini").answer("question", [])
