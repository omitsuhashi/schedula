from html.parser import HTMLParser
from http.client import HTTPConnection
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from demo import server
from tests.test_playground_server import http_server as http_server


class PageLinks(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.links = []
        self.ids = set()
        self.feed(content)

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if "id" in values:
            self.ids.add(values["id"])
        if tag in {"a", "link"} and "href" in values:
            self.links.append(values["href"])
        if tag == "script" and "src" in values:
            self.links.append(values["src"])


def get(instance, path):
    connection = HTTPConnection("127.0.0.1", instance.server_port, timeout=10)
    connection.request("GET", path)
    response = connection.getresponse()
    result = response.status, response.getheader("Content-Type"), response.read().decode("utf-8")
    connection.close()
    return result


def test_landing_links_reach_served_content_and_contact(http_server):
    for source in ("/", "/docs.html", "/demo/"):
        status, media_type, content = get(http_server, source)
        assert status == 200 and media_type == "text/html; charset=utf-8"
        page = PageLinks(content)
        for link in page.links:
            target = urlsplit(urljoin(source, link))
            if target.scheme == "mailto":
                assert unquote(target.path) == "omitsuhashi@the3-o.com"
                continue
            assert not target.scheme and not target.netloc, link
            status, media_type, body = get(http_server, target.path)
            assert status == 200, (source, link)
            if target.fragment and media_type.startswith("text/html"):
                # デモの主題IDはfeatures.jsが生成するため、実ブラウザーで確認する。
                if target.path != "/demo/":
                    assert target.fragment in PageLinks(body).ids, link

    page = PageLinks(get(http_server, "/")[2])
    (contact,) = [link for link in page.links if "body=" in link]
    query = parse_qs(urlsplit(contact).query)
    assert "導入・個別開発" in query["subject"][0]
    assert "ご相談内容" in query["body"][0]


def test_landing_documents_are_allowlisted_and_match_sources(http_server):
    for name in ("python-setup", "python-api", "io-contract-current", "distribution"):
        status, media_type, body = get(http_server, f"/docs/{name}.md")
        assert status == 200 and media_type == "text/plain; charset=utf-8"
        assert body == (server.ROOT / "docs" / f"{name}.md").read_text(encoding="utf-8")
    assert get(http_server, "/license.txt")[2] == (server.ROOT / "LICENSE").read_text()
    for path in (
        "/docs/../sources.md",
        "/docs/%2e%2e/sources.md",
        "/docs/sources.md",
        "/docs/reference/",
        "/.git/config",
    ):
        assert get(http_server, path)[0] == 404


def test_page_hierarchy_and_canonical_redirects(http_server):
    assert 'id="hero-title"' in get(http_server, "/")[2]
    assert 'id="feature-list"' in get(http_server, "/demo/")[2]
    for source, target in (("/demo", "/demo/"), ("/landing/", "/")):
        connection = HTTPConnection("127.0.0.1", http_server.server_port, timeout=10)
        connection.request("GET", source)
        response = connection.getresponse()
        assert response.status == 308 and response.getheader("Location") == target
        assert response.read() == b""
        connection.close()
    for path in ("/demo/../server.py", "/demo/%2e%2e/server.py", "/app.js", "/samples/lunch.json"):
        assert get(http_server, path)[0] == 404
