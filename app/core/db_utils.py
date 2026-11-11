from typing import Any, Callable

# Rows requested per round trip when a listing must return everything.
PAGE_SIZE = 1000


def fetch_all(build_query: Callable[[], Any], page_size: int = PAGE_SIZE) -> list[dict]:
    """Run a query page by page until the server returns an empty page.

    PostgREST silently caps a response at its `max-rows` setting (1000 by default),
    so a single request cannot be trusted to return a whole table. `build_query`
    must return a fresh builder each time, with a deterministic `.order()`.

    The loop advances by the number of rows actually received and stops only on
    an empty page, so it stays correct even if the server cap is below `page_size`.
    """
    rows: list[dict] = []
    while True:
        start = len(rows)
        page = build_query().range(start, start + page_size - 1).execute().data or []
        if not page:
            return rows
        rows.extend(page)


def single_row(data: Any) -> dict | None:
    """Normalize an RPC result that returns one row: PostgREST may answer an object or a one-item list."""
    if isinstance(data, list):
        return data[0] if data else None
    return data
