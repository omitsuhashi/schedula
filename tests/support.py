from shift_schedula.contract import schema_errors


def require_complete_demand(request):
    for item in request["demand"]:
        item["minimum_people"] = item["required_people"]
    return request


def assert_response(result, status):
    assert result["status"] == status
    assert not schema_errors("response", result)
    if status in {"OPTIMAL", "FEASIBLE", "PARTIAL"}:
        assert result["solution"] is not None
        assert result["verification"] == {"performed": True, "valid": True, "violations": []}
        proofs = [item["proven_optimal"] for item in result["objectives"]]
        assert proofs == sorted(proofs, reverse=True)
        if status == "OPTIMAL":
            assert all(proofs)
        elif status == "FEASIBLE" and proofs:
            assert not all(proofs)
    else:
        assert result["solution"] is None
        assert result["objectives"] == []
        assert result["verification"]["valid"] is not True
