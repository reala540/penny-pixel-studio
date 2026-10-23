import httpx

from studio.media import stock


def _client(routes):
    def handler(req: httpx.Request):
        for host, body in routes.items():
            if req.url.host == host:
                return httpx.Response(200, json=body) if isinstance(body, dict) else httpx.Response(200, content=body)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openverse_used_without_keys_and_only_public_domain(tmp_path, monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    results = {"results": [
        {"url": "https://img.example/by.jpg", "license": "by", "width": 4000, "height": 2000},
        {"url": "https://img.example/small.jpg", "license": "cc0", "width": 640, "height": 480},
        {"url": "https://img.example/good.jpg", "license": "cc0", "width": 3000, "height": 2000,
         "foreign_landing_url": "https://commons.example/good", "creator": "Ann", "source": "wikimedia", "title": "Coins"},
    ]}
    client = _client({"api.openverse.org": results, "img.example": b"jpegbytes"})
    hit = stock.find_photo("coins", tmp_path, client=client)
    assert hit is not None
    assert hit.provider == "openverse:wikimedia"
    assert hit.source_url == "https://commons.example/good"
    assert hit.attribution_required is False and "CC0" in hit.license
    assert hit.path.read_bytes() == b"jpegbytes"


def test_no_photo_returns_none(tmp_path, monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    client = _client({"api.openverse.org": {"results": []}})
    assert stock.find_photo("nothing", tmp_path, client=client) is None
