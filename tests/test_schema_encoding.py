from unittest.mock import Mock

import pytest

from shift_schedula import contract


@pytest.mark.parametrize("kind", ["request", "response"])
@pytest.mark.parametrize("schema_version", ["0.1", "0.2", "0.3", "0.4"])
def test_schema_reading_with_cp932_default(kind, schema_version, monkeypatch):
    schema_bytes = (
        contract.files("shift_schedula")
        .joinpath(f"schemas/{schema_version}/{kind}.schema.json")
        .read_bytes()
    )
    resource = Mock()
    resource.read_text.side_effect = lambda encoding=None: schema_bytes.decode(encoding or "cp932")
    root = Mock()
    root.joinpath.return_value = resource
    monkeypatch.setattr(contract, "files", lambda _: root)
    schema = contract.get_schema(kind, schema_version)
    assert schema["$id"] == f"urn:schedula:{kind}:{schema_version}"
    if kind == "request":
        expected = "需要は元の必要人数" if schema_version in {"0.3", "0.4"} else "需要は厳密な人数"
        assert expected in schema["description"]
