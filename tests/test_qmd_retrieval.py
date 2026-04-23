import subprocess

import pytest

from vault_curator import qmd_retrieval


def _completed(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["qmd"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_build_typed_query_collapses_multiline_input() -> None:
    typed_query = qmd_retrieval.build_typed_query(
        "인프라\n경제학",
        lex="기술적   에지",
    )

    assert typed_query == "lex: 기술적 에지\nvec: 인프라 경제학"


def test_fast_search_uses_typed_query_without_rerank(monkeypatch) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return _completed(
            stdout="""
Structured search: 2 queries (lex+vec)
[
  {
    "docid": "#83347d",
    "score": 1,
    "file": "qmd://synthesis/note.md",
    "title": "기술적 에지의 소멸",
    "context": "Synthesis context",
    "snippet": "title: \\"기술적 에지의 소멸\\""
  }
]
"""
        )

    monkeypatch.setattr(qmd_retrieval.subprocess, "run", fake_run)

    results = qmd_retrieval.fast_search(
        "인프라 경제학",
        lex="기술적 에지",
        collection="synthesis",
        limit=3,
        timeout_seconds=7,
    )

    assert results == [
        qmd_retrieval.QmdSearchResult(
            docid="#83347d",
            score=1.0,
            file="qmd://synthesis/note.md",
            title="기술적 에지의 소멸",
            context="Synthesis context",
            snippet='title: "기술적 에지의 소멸"',
        )
    ]
    args, kwargs = calls[0]
    assert args == [
        "qmd",
        "query",
        "lex: 기술적 에지\nvec: 인프라 경제학",
        "-c",
        "synthesis",
        "-n",
        "3",
        "--json",
        "--no-rerank",
    ]
    assert kwargs["capture_output"] is True
    assert kwargs["check"] is False
    assert kwargs["text"] is True
    assert kwargs["timeout"] == 7


def test_fast_retrieve_fetches_each_result_with_qmd_get(monkeypatch) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[1] == "query":
            return _completed(
                stdout="""
[
  {"score": 1, "file": "qmd://synthesis/one.md", "title": "One"},
  {"score": 0.5, "file": "qmd://synthesis/two.md", "title": "Two"}
]
"""
            )
        return _completed(stdout=f"body for {args[2]}")

    monkeypatch.setattr(qmd_retrieval.subprocess, "run", fake_run)

    documents = qmd_retrieval.fast_retrieve(
        "query",
        collection="synthesis",
        limit=2,
        get_lines=12,
    )

    assert [document.result.title for document in documents] == ["One", "Two"]
    assert [document.text for document in documents] == [
        "body for qmd://synthesis/one.md",
        "body for qmd://synthesis/two.md",
    ]
    assert calls[1] == [
        "qmd",
        "get",
        "qmd://synthesis/one.md",
        "-l",
        "12",
    ]
    assert calls[2] == [
        "qmd",
        "get",
        "qmd://synthesis/two.md",
        "-l",
        "12",
    ]


def test_fast_search_rejects_unscoped_collection(monkeypatch) -> None:
    def fake_run(args, **kwargs):
        raise AssertionError("qmd should not run")

    monkeypatch.setattr(qmd_retrieval.subprocess, "run", fake_run)

    with pytest.raises(qmd_retrieval.QmdRetrievalError, match="unsupported"):
        qmd_retrieval.fast_search("query", collection="everything")


def test_qmd_failure_is_wrapped(monkeypatch) -> None:
    def fake_run(args, **kwargs):
        return _completed(stderr="missing collection", returncode=1)

    monkeypatch.setattr(qmd_retrieval.subprocess, "run", fake_run)

    with pytest.raises(qmd_retrieval.QmdRetrievalError, match="missing collection"):
        qmd_retrieval.fast_search("query", collection="synthesis")
