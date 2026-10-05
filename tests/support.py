from schedula.contract import schema_errors


def assert_response(result, status):
    assert result["status"] == status
    assert not schema_errors("response", result)
    if status == "OPTIMAL":
        assert result["solution"] is not None
        assert result["verification"] == {"performed": True, "valid": True, "violations": []}
        assert all(item["proven_optimal"] for item in result["objectives"])
    else:
        assert result["solution"] is None
        assert result["objectives"] == []
        assert result["verification"]["valid"] is not True
