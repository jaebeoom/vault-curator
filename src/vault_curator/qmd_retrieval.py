"""Safe qmd sidecar retrieval for Vault notes.

The adapter intentionally uses qmd's typed ``lex`` + ``vec`` query form with
reranking disabled. Plain natural-language ``qmd query`` can trigger slow model
downloads and query expansion, so automation should route through this module.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


DEFAULT_COLLECTION = "synthesis"
SUPPORTED_COLLECTIONS = frozenset(
    {
        "synthesis",
        "polaris",
        "capture",
        "reference",
    }
)
DEFAULT_LIMIT = 5
DEFAULT_GET_LINES = 80
DEFAULT_TIMEOUT_SECONDS = 30


class QmdRetrievalError(RuntimeError):
    """Raised when qmd cannot return usable retrieval results."""


@dataclass(frozen=True)
class QmdSearchResult:
    docid: str
    score: float
    file: str
    title: str
    context: str
    snippet: str


@dataclass(frozen=True)
class QmdRetrievedDocument:
    result: QmdSearchResult
    text: str


def build_typed_query(query: str, lex: str | None = None) -> str:
    """Build qmd's typed search document without enabling query expansion."""
    vector_query = _single_line(query)
    lexical_query = _single_line(lex) if lex is not None else vector_query
    if not vector_query:
        raise QmdRetrievalError("qmd query cannot be empty")
    if not lexical_query:
        raise QmdRetrievalError("qmd lexical query cannot be empty")
    return f"lex: {lexical_query}\nvec: {vector_query}"


def fast_search(
    query: str,
    *,
    lex: str | None = None,
    collection: str = DEFAULT_COLLECTION,
    limit: int = DEFAULT_LIMIT,
    qmd_bin: str = "qmd",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[QmdSearchResult]:
    """Run bounded qmd search with fast defaults."""
    _validate_collection(collection)
    _validate_positive("limit", limit)
    typed_query = build_typed_query(query, lex)
    completed = _run_qmd(
        [
            "query",
            typed_query,
            "-c",
            collection,
            "-n",
            str(limit),
            "--json",
            "--no-rerank",
        ],
        qmd_bin=qmd_bin,
        timeout_seconds=timeout_seconds,
    )
    payload = _extract_json_array(completed.stdout)
    return [_result_from_mapping(item) for item in payload]


def get_document(
    file_uri: str,
    *,
    lines: int = DEFAULT_GET_LINES,
    qmd_bin: str = "qmd",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Fetch the concrete qmd document text for citation/use."""
    if not file_uri.strip():
        raise QmdRetrievalError("qmd document URI cannot be empty")
    _validate_positive("lines", lines)
    completed = _run_qmd(
        [
            "get",
            file_uri,
            "-l",
            str(lines),
        ],
        qmd_bin=qmd_bin,
        timeout_seconds=timeout_seconds,
    )
    return completed.stdout


def fast_retrieve(
    query: str,
    *,
    lex: str | None = None,
    collection: str = DEFAULT_COLLECTION,
    limit: int = DEFAULT_LIMIT,
    get_lines: int = DEFAULT_GET_LINES,
    qmd_bin: str = "qmd",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[QmdRetrievedDocument]:
    """Search, then fetch the matching source documents."""
    results = fast_search(
        query,
        lex=lex,
        collection=collection,
        limit=limit,
        qmd_bin=qmd_bin,
        timeout_seconds=timeout_seconds,
    )
    return [
        QmdRetrievedDocument(
            result=result,
            text=get_document(
                result.file,
                lines=get_lines,
                qmd_bin=qmd_bin,
                timeout_seconds=timeout_seconds,
            ),
        )
        for result in results
    ]


def _run_qmd(
    args: list[str],
    *,
    qmd_bin: str,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            [qmd_bin, *args],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise QmdRetrievalError(
            f"qmd binary not found: {qmd_bin}. Install @tobilu/qmd first."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise QmdRetrievalError(
            f"qmd timed out after {timeout_seconds}s"
        ) from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        if detail:
            raise QmdRetrievalError(f"qmd failed: {detail}")
        raise QmdRetrievalError(f"qmd failed with exit code {completed.returncode}")
    return completed


def _extract_json_array(stdout: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char != "[":
            continue
        try:
            parsed, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            if not all(isinstance(item, dict) for item in parsed):
                raise QmdRetrievalError("qmd JSON result must be an object array")
            return parsed
    raise QmdRetrievalError("qmd did not return a JSON result array")


def _result_from_mapping(item: dict[str, Any]) -> QmdSearchResult:
    try:
        return QmdSearchResult(
            docid=str(item.get("docid", "")),
            score=float(item.get("score", 0.0)),
            file=str(item["file"]),
            title=str(item.get("title", "")),
            context=str(item.get("context", "")),
            snippet=str(item.get("snippet", "")),
        )
    except KeyError as exc:
        raise QmdRetrievalError("qmd result is missing required field: file") from exc
    except (TypeError, ValueError) as exc:
        raise QmdRetrievalError("qmd result has an invalid score") from exc


def _validate_collection(collection: str) -> None:
    if collection not in SUPPORTED_COLLECTIONS:
        supported = ", ".join(sorted(SUPPORTED_COLLECTIONS))
        raise QmdRetrievalError(
            f"unsupported qmd collection: {collection}. Supported: {supported}"
        )


def _validate_positive(name: str, value: int) -> None:
    if value < 1:
        raise QmdRetrievalError(f"{name} must be at least 1")


def _single_line(value: str | None) -> str:
    return " ".join((value or "").split())
