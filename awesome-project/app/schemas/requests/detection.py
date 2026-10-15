from pydantic import BaseModel


class DetectRequest(BaseModel):
    """Options for one detection run — `POST /…/submissions/{id}/detect`.

    A JSON body rather than `?force=true`: §5 of `docs/API_CONVENTIONS.md`
    reserves query parameters for `GET` filtering/sorting/pagination, and this
    is a mutation's input. It was the last endpoint still taking one from the
    query string (`?note=` was fixed the same way), and
    `tests/test_api_contract.py` now fails if a new one appears.

    The whole body is optional: detection with no options is the common case,
    so a body-less `POST` must keep working.
    """

    force: bool = False
    """Re-run even if a result already exists. Useful after the detector or its
    weights change — otherwise the stored result is returned and no CPU is
    spent recomputing it."""
