"""fetcher 数据返回契约 (P0-B 规范整改, 2026-09-11)

规范 §4: 采集层应统一返回结构, 迁移期可适配器兼容。
规范 §4: 状态 ok/empty/error/unsupported, 字段 status/data/source/as_of/fetched_at/scope/units/error

本模块:
1. 4 状态枚举常量
2. 标准返回 dict 构造器 make_result(...)
3. 错误对象构造器 make_error(code, message, retryable)
4. 旧格式 adapter: from_legacy(blob) 兼容 {"error": str, "rows": []} 老 fetcher
5. 调用方检测函数: is_error(blob) / is_empty(blob) / status(blob)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

# 4 状态常量 (§4 规范)
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_ERROR = "error"
STATUS_UNSUPPORTED = "unsupported"

VALID_STATUSES = {STATUS_OK, STATUS_EMPTY, STATUS_ERROR, STATUS_UNSUPPORTED}

# 错误码枚举 (§4 规范 '稳定错误码')
ERR_NET_TIMEOUT = "NET_TIMEOUT"
ERR_NET_SSL = "NET_SSL"
ERR_NET_CONN = "NET_CONN"
ERR_NET_5XX = "NET_5XX"
ERR_NET_4XX = "NET_4XX"
ERR_NET_RATELIMIT = "NET_RATELIMIT"
ERR_PARSE = "PARSE"
ERR_VALIDATION = "VALIDATION"
ERR_UNSUPPORTED = "UNSUPPORTED"
ERR_UNKNOWN = "UNKNOWN"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def make_error(code: str, message: str, retryable: bool = True) -> Dict[str, Any]:
    """§4 错误对象: 稳定错误码 + 可读消息 + retryable"""
    return {"code": code, "message": str(message)[:200], "retryable": bool(retryable)}


def make_result(
    *,
    status: str,
    data: Any = None,
    source: str = "",
    as_of: Optional[str] = None,
    fetched_at: Optional[str] = None,
    scope: str = "stock",
    units: Optional[Dict[str, str]] = None,
    error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """§4 标准返回 dict 构造器

    字段:
      status: ok/empty/error/unsupported
      data: 业务数据 (ok/empty 时填, error 时 None)
      source: 'provider.endpoint' (e.g. 'eastmoney.datacenter')
      as_of: 数据时点 (ISO 日期), 未知时 None
      fetched_at: 采集时间 (ISO 完整时间戳)
      scope: stock/industry/market/sector
      units: 单位字典 (e.g. {'amount': 'CNY', 'pct': '%'})
      error: 错误对象 (status=error/unsupported 时填)
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status!r}, must be one of {VALID_STATUSES}")
    return {
        "status": status,
        "data": data,
        "source": source,
        "as_of": as_of,
        "fetched_at": fetched_at or _now_iso(),
        "scope": scope,
        "units": units or {},
        "error": error,
    }


def make_ok(
    data: Any,
    *,
    source: str = "",
    as_of: Optional[str] = None,
    scope: str = "stock",
    units: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """§4 成功返回"""
    return make_result(
        status=STATUS_OK, data=data, source=source, as_of=as_of,
        scope=scope, units=units,
    )


def make_empty(
    *,
    source: str = "",
    as_of: Optional[str] = None,
    scope: str = "stock",
    reason: str = "该期间无记录",
) -> Dict[str, Any]:
    """§4 空结果返回 (请求+解析成功, 业务确认无记录)"""
    return make_result(
        status=STATUS_EMPTY, data=None, source=source, as_of=as_of,
        scope=scope,
        error=make_error(ERR_VALIDATION, reason, retryable=False),
    )


def make_error_result(
    code: str,
    message: str,
    *,
    source: str = "",
    retryable: bool = True,
    scope: str = "stock",
) -> Dict[str, Any]:
    """§4 错误返回"""
    return make_result(
        status=STATUS_ERROR, data=None, source=source,
        scope=scope,
        error=make_error(code, message, retryable=retryable),
    )


def make_unsupported(
    *,
    source: str = "",
    scope: str = "stock",
    reason: str = "数据源或标的不支持此能力",
) -> Dict[str, Any]:
    """§4 不支持返回 (e.g. 小盘无融资融券)"""
    return make_result(
        status=STATUS_UNSUPPORTED, data=None, source=source,
        scope=scope,
        error=make_error(ERR_UNSUPPORTED, reason, retryable=False),
    )


# ============================================================
# 检测函数 (§4 '调用方必须检查状态, 而非只检查是否抛异常')
# ============================================================
def status_of(blob: Any) -> Optional[str]:
    """返回 blob 的 status 字段; 老格式 blob 推导 status"""
    if blob is None:
        return None
    if not isinstance(blob, dict):
        return None
    if "status" in blob and blob["status"] in VALID_STATUSES:
        return blob["status"]
    # 老格式 {"error": str, "rows": []} 推导
    return _legacy_status(blob)


def is_ok(blob: Any) -> bool:
    return status_of(blob) == STATUS_OK


def is_empty(blob: Any) -> bool:
    return status_of(blob) == STATUS_EMPTY


def is_error(blob: Any) -> bool:
    """§4 '错误返回不等于成功; 调用方必须检查状态, 而非只检查是否抛异常'

    约定: None / 非 dict 也视为 error (与 v3 老 _is_error 行为兼容 — 数据缺失 = 失败)。
    严格的 '未知状态' 用 status_of(blob) is None 区分。
    """
    if blob is None or not isinstance(blob, dict):
        return True
    st = status_of(blob)
    if st is None:
        return True  # 不可解析视为 error
    return st == STATUS_ERROR


def is_unsupported(blob: Any) -> bool:
    return status_of(blob) == STATUS_UNSUPPORTED


# ============================================================
# 老格式 adapter (§4 迁移期兼容)
# ============================================================
def _legacy_status(blob: Dict[str, Any]) -> str:
    """从老 ad-hoc 格式推导 status"""
    # {"error": str} 形式
    if isinstance(blob.get("error"), str):
        return STATUS_ERROR
    # {"data": {...}} 但 data 缺失/空
    if "rows" in blob and isinstance(blob.get("rows"), list):
        if not blob["rows"]:
            return STATUS_EMPTY
        return STATUS_OK
    if "data" in blob and isinstance(blob.get("data"), list):
        if not blob["data"]:
            return STATUS_EMPTY
        return STATUS_OK
    # 兜底: 视为 ok (向后兼容, 但记录 warning)
    return STATUS_OK


def from_legacy(blob: Any, *, source: str = "legacy") -> Dict[str, Any]:
    """§4 '迁移期可适配器兼容旧接口' — 把老 ad-hoc blob 转新契约

    支持老格式:
      {"error": "msg", "rows": [...]}  → status=error (or empty if rows=[])
      {"error": "msg"}                  → status=error
      {"rows": [...]}                   → status=ok/empty
      {"data": {...}}                   → status=ok
      None                               → status=error (UNKNOWN)
    """
    if blob is None:
        return make_error_result(ERR_UNKNOWN, "legacy blob is None", source=source, retryable=False)

    if isinstance(blob, dict) and "status" in blob and blob["status"] in VALID_STATUSES:
        return blob  # 已经是新契约, 直接返回

    if not isinstance(blob, dict):
        return make_error_result(ERR_VALIDATION, f"legacy blob type {type(blob).__name__}",
                                 source=source, retryable=False)

    # 推导 status
    legacy = _legacy_status(blob)
    if legacy == STATUS_ERROR:
        msg = blob.get("error", "未知错误")
        return make_error_result(ERR_UNKNOWN, str(msg), source=source)
    if legacy == STATUS_EMPTY:
        return make_empty(source=source, reason=str(blob.get("error", "无记录")))
    # ok — data 字段统一
    data = blob.get("data")
    if data is None:
        data = {
            "rows": blob.get("rows", []),
            "announcements": blob.get("announcements", []),
        }
    return make_ok(data, source=source)
