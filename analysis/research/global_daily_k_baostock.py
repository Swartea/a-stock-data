"""BaoStock fallback fetcher for the four registered A-share indices.

BaoStock keeps process-global socket/session state and does not expose a
request deadline. Each query therefore runs in a fresh ``spawn`` child. The
parent enforces a hard deadline and reaps the child before returning.
"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import date as Date
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from analysis import fetcher_contract

from .global_daily_k import (
    _coerce_finite_number,
    _normalize_now,
    _parse_strict_date,
    _validate_inputs,
)
from .global_indices import GlobalIndexSpec, get_global_index

BAOSTOCK_PROVIDER_ID = "baostock"
BAOSTOCK_SOURCE = "baostock.daily_k"
BAOSTOCK_SCOPE = "market"
BAOSTOCK_HARD_TIMEOUT_SECONDS = 10.0
BAOSTOCK_INDEX_CODES: dict[str, str] = {
    "cn.index.sse.000001": "sh.000001",
    "cn.index.szse.399001": "sz.399001",
    "cn.index.szse.399006": "sz.399006",
    "cn.index.csi.000300": "sh.000300",
}
_BAOSTOCK_FIELDS = "date,code,open,high,low,close,volume,amount"
_UNITS = {"price": "index_points", "volume": "unavailable"}
_Worker = Callable[..., Any]


def _query_baostock(code: str, start_date: str, end_date: str) -> dict[str, Any]:
    """Run SDK login/query/logout and return a small picklable protocol value."""

    # Import in the child so the parent never initializes BaoStock's singleton
    # socket or inherits an SDK session.
    import io

    import baostock as bs

    logged_in = False
    # BaoStock catches some socket exceptions and prints them. Keep those
    # provider internals out of the caller's terminal and result envelope.
    from contextlib import redirect_stderr, redirect_stdout

    with redirect_stdout(io.StringIO()), redirect_stderr(
        io.StringIO()
    ):
        try:
            login = bs.login()
            if getattr(login, "error_code", None) != "0":
                return {"status": "login_error"}
            logged_in = True

            result = bs.query_history_k_data_plus(
                code,
                _BAOSTOCK_FIELDS,
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="3",
            )
            error_code = getattr(result, "error_code", None)
            if error_code != "0":
                return {"status": "query_error"}
            fields = getattr(result, "fields", None)
            if not isinstance(fields, list) or not fields:
                return {"status": "malformed"}

            rows: list[dict[str, str]] = []
            while result.next():
                values = result.get_row_data()
                if not isinstance(values, list) or len(values) != len(fields):
                    return {"status": "malformed"}
                rows.append(dict(zip(fields, values, strict=True)))
            return {"status": "ok", "rows": rows}
        except Exception:
            # BaoStock has broad internal exception handling. If an exception
            # escapes the SDK boundary, do not serialize its text or internals.
            return {"status": "worker_error"}
        finally:
            if logged_in:
                with suppress(Exception):
                    bs.logout()


def _child_entry(connection: Any, worker: _Worker, args: tuple[Any, ...]) -> None:
    """Multiprocessing target; contain exceptions and send one serializable value."""

    try:
        connection.send(("ok", worker(*args)))
    except Exception:
        with suppress(Exception):
            connection.send(("worker_error", None))
    finally:
        connection.close()


def _run_baostock_child(
    worker: _Worker,
    *args: Any,
    timeout_seconds: float = BAOSTOCK_HARD_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run a picklable worker in a fresh process with a hard wall deadline.

    ``worker`` and ``args`` form a private test seam; production always uses
    :func:`_query_baostock` and the fixed ten-second limit.
    """

    if not callable(worker):
        return {"status": "worker_error"}
    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds, (int, float)
    ) or timeout_seconds <= 0:
        return {"status": "worker_error"}

    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_child_entry,
        args=(child_connection, worker, tuple(args)),
        daemon=True,
    )
    started = time.monotonic()
    timed_out = False
    try:
        process.start()
        child_connection.close()
        remaining = max(0.0, timeout_seconds - (time.monotonic() - started))
        process.join(remaining)
        if process.is_alive():
            timed_out = True
            process.terminate()
            process.join(0.25)
        if process.is_alive():
            process.kill()
            process.join()

        if timed_out:
            return {"status": "timeout"}
        if process.exitcode is None:
            return {"status": "worker_error"}
        if process.exitcode != 0:
            return {"status": "worker_error"}
        if not parent_connection.poll():
            return {"status": "worker_error"}
        try:
            status, payload = parent_connection.recv()
        except (EOFError, OSError):
            return {"status": "worker_error"}
        if status != "ok" or not isinstance(payload, Mapping):
            return {"status": "worker_error"}
        return dict(payload)
    except Exception:
        if process.pid is not None and process.is_alive():
            process.terminate()
            process.join(0.25)
            if process.is_alive():
                process.kill()
                process.join()
        return {"status": "worker_error"}
    finally:
        parent_connection.close()
        with suppress(OSError):
            child_connection.close()
        if process.pid is not None and not process.is_alive():
            process.close()


def _error(code: str, message: str, *, retryable: bool) -> dict[str, Any]:
    return fetcher_contract.make_error_result(
        code,
        message,
        source=BAOSTOCK_SOURCE,
        retryable=retryable,
        scope=BAOSTOCK_SCOPE,
    )


def _parse_row(row: Any, *, code: str) -> tuple[Date, dict[str, float]]:
    if not isinstance(row, Mapping):
        raise ValueError("row must be a mapping")
    if row.get("code") != code:
        raise ValueError("provider symbol did not match request")
    session = _parse_strict_date(row.get("date"), field="row date")
    values = {
        name: _coerce_finite_number(row.get(name), field=name)
        for name in ("open", "high", "low", "close")
    }
    if values["low"] > values["high"]:
        raise ValueError("low must be <= high")
    if values["low"] > values["open"] or values["low"] > values["close"]:
        raise ValueError("low must be <= open and close")
    if values["high"] < values["open"] or values["high"] < values["close"]:
        raise ValueError("high must be >= open and close")
    return session, values


def fetch_baostock_daily_k(
    index_id: str,
    start_date: str,
    end_date: str,
    *,
    now: datetime | None = None,
    transport: Any = None,
) -> dict[str, Any]:
    """Fetch normalized Daily-K for one of the four supported A-share indices."""

    # The shared V1 gate owns strict dates, aware-now, ordering and window cap.
    # BaoStock has no HTTP transport; a sentinel callable preserves that gate.
    validation_transport = (lambda *_args, **_kwargs: None) if transport is None else transport
    try:
        _validate_inputs(
            index_id, start_date, end_date, validation_transport, now
        )
    except (TypeError, ValueError) as exc:
        return _error(fetcher_contract.ERR_VALIDATION, str(exc), retryable=False)

    try:
        spec: GlobalIndexSpec = get_global_index(index_id)
    except KeyError as exc:
        return fetcher_contract.make_unsupported(
            source=BAOSTOCK_SOURCE,
            scope=BAOSTOCK_SCOPE,
            reason=str(exc),
        )
    except (TypeError, ValueError) as exc:
        return _error(fetcher_contract.ERR_VALIDATION, str(exc), retryable=False)

    code = BAOSTOCK_INDEX_CODES.get(index_id)
    if code is None:
        return fetcher_contract.make_unsupported(
            source=BAOSTOCK_SOURCE,
            scope=BAOSTOCK_SCOPE,
            reason="BaoStock Daily-K supports only the four registered A-share indices",
        )
    try:
        start = _parse_strict_date(start_date, field="start_date")
        end = _parse_strict_date(end_date, field="end_date")
        local_cutoff = _normalize_now(now).astimezone(ZoneInfo(spec.timezone)).date()
    except (TypeError, ValueError):
        return _error(
            fetcher_contract.ERR_VALIDATION,
            "invalid BaoStock Daily-K request",
            retryable=False,
        )

    try:
        protocol = _run_baostock_child(
            _query_baostock, code, start_date, end_date
        )
    except Exception:
        return _error(
            fetcher_contract.ERR_UNKNOWN,
            "BaoStock Daily-K worker failed",
            retryable=True,
        )
    if not isinstance(protocol, Mapping):
        return _error(
            fetcher_contract.ERR_UNKNOWN,
            "BaoStock Daily-K worker returned no valid response",
            retryable=True,
        )
    status = protocol.get("status")
    if status == "timeout":
        return _error(
            fetcher_contract.ERR_NET_TIMEOUT,
            "BaoStock Daily-K request timed out",
            retryable=True,
        )
    if status == "login_error":
        return _error(
            fetcher_contract.ERR_NET_CONN,
            "BaoStock login failed",
            retryable=True,
        )
    if status == "query_error":
        return _error(
            fetcher_contract.ERR_UNKNOWN,
            "BaoStock Daily-K query failed",
            retryable=True,
        )
    if status == "malformed":
        return _error(
            fetcher_contract.ERR_PARSE,
            "BaoStock Daily-K response has an invalid schema",
            retryable=False,
        )
    if status != "ok" or not isinstance(protocol.get("rows"), list):
        return _error(
            fetcher_contract.ERR_UNKNOWN,
            "BaoStock Daily-K worker returned no valid response",
            retryable=True,
        )

    parsed: dict[Date, dict[str, float]] = {}
    for row in protocol["rows"]:
        try:
            session, values = _parse_row(row, code=code)
        except (TypeError, ValueError):
            return _error(
                fetcher_contract.ERR_PARSE,
                "BaoStock Daily-K response contains a malformed row",
                retryable=False,
            )
        if session < start or session > end or session >= local_cutoff:
            continue
        existing = parsed.get(session)
        if existing is not None and existing != values:
            return _error(
                fetcher_contract.ERR_PARSE,
                "BaoStock Daily-K response has conflicting duplicate dates",
                retryable=False,
            )
        parsed[session] = values

    records = [
        {
            "index_id": spec.identity.index_id,
            "market": spec.market,
            "symbol": spec.identity.local_code,
            "name": spec.name,
            "date": session.isoformat(),
            **parsed[session],
            "volume": None,
            "currency": spec.currency,
            "timezone": spec.timezone,
            "source": BAOSTOCK_SOURCE,
        }
        for session in sorted(parsed)
    ]
    if not records:
        return fetcher_contract.make_empty(
            source=BAOSTOCK_SOURCE,
            scope=BAOSTOCK_SCOPE,
            reason="no BaoStock Daily-K rows in window",
        )
    return fetcher_contract.make_ok(
        records,
        source=BAOSTOCK_SOURCE,
        as_of=records[-1]["date"],
        scope=BAOSTOCK_SCOPE,
        units=dict(_UNITS),
    )


def baostock_daily_k_provider() -> Any:
    """Return the V2 provider descriptor without importing V2 at module load."""

    from .global_daily_k_service import DailyKProvider

    return DailyKProvider(
        name=BAOSTOCK_PROVIDER_ID,
        source=BAOSTOCK_SOURCE,
        scope=BAOSTOCK_SCOPE,
        fetch=fetch_baostock_daily_k,
    )


__all__ = [
    "BAOSTOCK_HARD_TIMEOUT_SECONDS",
    "BAOSTOCK_INDEX_CODES",
    "BAOSTOCK_PROVIDER_ID",
    "BAOSTOCK_SCOPE",
    "BAOSTOCK_SOURCE",
    "baostock_daily_k_provider",
    "fetch_baostock_daily_k",
]
