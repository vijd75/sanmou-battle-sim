import http.client
import json
import threading
from contextlib import contextmanager

from web import server as server_module


@contextmanager
def running_server():
    server = server_module.ThreadingHTTPServer(("127.0.0.1", 0), server_module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def post_json(server, payload, origin=None):
    origin = origin or f"http://{server.server_address[0]}:{server.server_address[1]}"
    connection = http.client.HTTPConnection(*server.server_address)
    body = json.dumps(payload).encode("utf-8")
    connection.request("POST", "/api/arena/advisor", body, {"Content-Type": "application/json", "Origin": origin})
    response = connection.getresponse()
    result = response.status, json.loads(response.read().decode("utf-8"))
    connection.close()
    return result


def test_advisor_prompt_includes_source_labeled_team_systems():
    prompt = server_module.build_arena_advisor_prompt({"generals": [], "skills": []})

    for system in ["汉盾", "司马懿体系", "姜维体系", "左慈主动战法体系", "赵云体系", "陆逊火系体系"]:
        assert system in prompt
    assert "BV1XXNs6rEHZ" in prompt
    assert "BV1QHeg6qEpF" in prompt
    assert "不能将频率解释为胜率" in prompt
    assert "不要根据阵容图模糊小字" in prompt


def test_advisor_prompt_includes_full_card_indexes_and_expands_draft_candidates():
    context = {
        "generals": [],
        "skills": [],
        "currentDraftOptions": {
            "kind": "武将",
            "candidateGroups": [["曹操", "司马懿", "张春华"], [], []],
        },
    }
    catalog = server_module.build_arena_catalog_context(context)
    prompt = server_module.build_arena_advisor_prompt(context)

    assert catalog["counts"] == {"generals": 102, "skills": 233}
    assert len(catalog["general_index"]) == 102
    assert len(catalog["skill_index"]) == 233
    assert {item["name"] for item in catalog["referenced_general_details"]} == {"曹操", "司马懿", "张春华"}
    assert "曹操" in prompt
    assert "完整属性、原文和结构化效果" in prompt


def test_advisor_prompt_expands_cards_mentioned_in_chat():
    catalog = server_module.build_arena_catalog_context({"generals": [], "skills": []}, "比较姜维和草船借箭")

    assert [item["name"] for item in catalog["referenced_general_details"]] == ["姜维"]
    assert any(item["name"] == "草船借箭" for item in catalog["referenced_skill_details"])


def test_advisor_proxy_forwards_current_context_and_hides_api_key(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "优先围绕核心武将构筑。"}}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(server_module.urllib.request, "urlopen", fake_urlopen)
    payload = {
        "endpoint": "https://model.example/v1/chat/completions",
        "model": "test-model",
        "api_key": "private-test-key",
        "messages": [{"role": "user", "content": "分析现有卡池"}],
        "context": {"generals": [{"name": "姜维"}], "skills": []},
    }

    with running_server() as server:
        status, result = post_json(server, payload)

    assert status == 200
    assert result == {"reply": "优先围绕核心武将构筑。"}
    assert captured["url"] == payload["endpoint"]
    assert captured["headers"]["Authorization"] == "Bearer private-test-key"
    assert captured["body"]["model"] == "test-model"
    assert "姜维" in captured["body"]["messages"][0]["content"]
    assert "private-test-key" not in json.dumps(result)
    assert captured["timeout"] == 90


def test_advisor_proxy_rejects_remote_http_endpoint(monkeypatch):
    def unexpected_urlopen(*_args, **_kwargs):
        raise AssertionError("insecure endpoint must not be called")

    monkeypatch.setattr(server_module.urllib.request, "urlopen", unexpected_urlopen)
    payload = {
        "endpoint": "http://model.example/v1/chat/completions",
        "model": "test-model",
        "messages": [{"role": "user", "content": "分析"}],
        "context": {},
    }

    with running_server() as server:
        status, result = post_json(server, payload)

    assert status == 400
    assert "HTTPS" in result["error"]


def test_advisor_proxy_rejects_cross_origin_request():
    payload = {"endpoint": "https://model.example/v1/chat/completions", "model": "test", "messages": [], "context": {}}

    with running_server() as server:
        status, result = post_json(server, payload, origin="https://untrusted.example")

    assert status == 403
    assert "本地页面" in result["error"]


def test_advisor_proxy_allows_known_local_ui_origin(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "收到。"}}]}).encode("utf-8")

    monkeypatch.setattr(server_module.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    payload = {
        "endpoint": "https://model.example/v1/chat/completions",
        "model": "test-model",
        "messages": [{"role": "user", "content": "分析卡池"}],
        "context": {},
    }

    with running_server() as server:
        status, result = post_json(server, payload, origin="http://127.0.0.1:8000")

    assert status == 200
    assert result == {"reply": "收到。"}


def test_advisor_proxy_preflight_only_allows_known_local_ui_origin():
    with running_server() as server:
        connection = http.client.HTTPConnection(*server.server_address)
        connection.request("OPTIONS", "/api/arena/advisor", headers={"Origin": "http://127.0.0.1:8000"})
        response = connection.getresponse()
        assert response.status == 204
        assert response.getheader("Access-Control-Allow-Origin") == "http://127.0.0.1:8000"
        response.read()
        connection.close()
