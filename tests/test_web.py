import http.client
import json
import threading

import pytest

from ai_memory import index, web


@pytest.fixture
def port():
    srv = web.create_server(port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def get(port, path, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest("GET", path, skip_host=host is not None)
    if host is not None:
        conn.putheader("Host", host)
    conn.endheaders()
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, {k.lower(): v for k, v in resp.getheaders()}, body


def api(port, query=""):
    status, _, body = get(port, "/api/audit" + query)
    return status, json.loads(body)


def test_page_is_served_with_hardening_headers(port):
    status, headers, body = get(port, "/")
    assert status == 200 and b"ai-memory" in body
    assert headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in headers["content-security-policy"]


def test_empty_home_returns_zero_stats_not_an_error(port):
    status, data = api(port)
    assert status == 200 and data["stats"]["total"] == 0 and data["rows"] == []


def test_lists_newest_first_and_filters(port):
    index.audit("search_memory", llm="Claude", project="p", query="sqlite", result_count=2)
    index.audit("get_handoff", llm="Codex", project="q", result_count=1)
    index.audit("search_memory", llm="Claude", project="p", query="boom", ok=False, error="bad")

    _, data = api(port)
    assert data["stats"] == {"total": 3, "unique_queries": 2, "callers": 2, "projects": 2}
    assert [r["query"] for r in data["rows"]][0] == "boom"

    assert api(port, "?llm=Codex")[1]["stats"]["total"] == 1
    assert api(port, "?tool=get_handoff")[1]["rows"][0]["project"] == "q"
    assert api(port, "?status=failed")[1]["rows"][0]["error"] == "bad"
    assert api(port, "?status=success")[1]["stats"]["total"] == 2
    assert [r["query"] for r in api(port, "?query=sql")[1]["rows"]] == ["sqlite"]


def test_query_filter_treats_wildcards_literally(port):
    index.audit("search_memory", query="plain")
    index.audit("search_memory", query="100% sure")
    rows = api(port, "?query=%25")[1]["rows"]
    assert [r["query"] for r in rows] == ["100% sure"]


def test_limit_is_clamped_and_garbage_falls_back(port):
    for i in range(3):
        index.audit("recent", query=str(i))
    assert len(api(port, "?limit=0")[1]["rows"]) == 1
    assert len(api(port, "?limit=abc")[1]["rows"]) == 3


def test_foreign_host_header_is_refused(port):
    for path in ("/", "/api/audit"):
        assert get(port, path, host="evil.example:8765")[0] == 403
        assert get(port, path, host="evil.example")[0] == 403
    assert get(port, "/api/audit", host=f"localhost:{port}")[0] == 200
    assert get(port, "/api/audit", host=f"127.0.0.1:{port}")[0] == 200


def test_unknown_path_is_404(port):
    assert get(port, "/nope")[0] == 404
    assert get(port, "/../../etc/passwd")[0] == 404


def test_viewing_the_page_does_not_write_audit_rows(port):
    index.audit("recent", query="seed")
    before = api(port)[1]["stats"]["total"]
    api(port)
    api(port, "?llm=x")
    assert api(port)[1]["stats"]["total"] == before
