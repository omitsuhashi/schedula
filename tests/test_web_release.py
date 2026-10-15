import pytest

from scripts import check_web_release


@pytest.mark.parametrize("tag", ["v1.0.0", "web-v01.0.0", "web-v1.0.0-rc1", "main", "--help"])
def test_web_tags_do_not_overlap_pypi(tag):
    with pytest.raises(ValueError):
        check_web_release.check(tag, "the3-inc/schedula")


def test_web_release_requires_main_and_latest_success(monkeypatch):
    import json

    sha = "a" * 40
    calls = []

    def command(*args):
        calls.append(args)
        if args[0] == "git":
            return sha
        return json.dumps(
            {
                "workflow_runs": [
                    {"id": 1, "path": ".github/workflows/ci.yml", "conclusion": "success"},
                    {"id": 2, "path": ".github/workflows/ci.yml", "conclusion": "failure"},
                ]
            }
        )

    monkeypatch.setattr(check_web_release, "command", command)
    ancestry = []
    monkeypatch.setattr(
        check_web_release.subprocess, "run", lambda args, **kwargs: ancestry.append(args)
    )
    with pytest.raises(ValueError, match="main CI"):
        check_web_release.check("web-v1.0.0", "the3-inc/schedula")
    assert ancestry == [["git", "merge-base", "--is-ancestor", sha, "origin/main"]]
    assert "event=push&branch=main" in calls[-1][2]

    monkeypatch.setattr(
        check_web_release,
        "command",
        lambda *args: (
            sha
            if args[0] == "git"
            else json.dumps(
                {
                    "workflow_runs": [
                        {"id": 3, "path": ".github/workflows/ci.yml", "conclusion": "success"}
                    ]
                }
            )
        ),
    )
    assert check_web_release.check("web-v1.0.0", "the3-inc/schedula") == sha
    monkeypatch.setattr(
        check_web_release,
        "command",
        lambda *args: sha if args[0] == "git" else json.dumps({"workflow_runs": []}),
    )
    with pytest.raises(ValueError, match="main CI"):
        check_web_release.check("web-v1.0.0", "the3-inc/schedula")
