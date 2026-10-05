from unittest.mock import Mock

import pytest

from schedula import contract


@pytest.mark.parametrize("kind", ["request", "response"])
def test_schema_reading_with_cp932_default(kind, monkeypatch):
    schema_bytes = (
        contract.files("schedula").joinpath(f"schemas/0.1/{kind}.schema.json").read_bytes()
    )
    resource = Mock()
    resource.read_text.side_effect = lambda encoding=None: schema_bytes.decode(encoding or "cp932")
    root = Mock()
    root.joinpath.return_value = resource
    monkeypatch.setattr(contract, "files", lambda _: root)
    schema = contract.get_schema(kind)
    assert schema["$id"] == f"urn:schedula:{kind}:0.1"
    if kind == "request":
        assert "需要は厳密な人数" in schema["description"]
