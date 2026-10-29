# analysis/sections/__init__.py
"""Section Registry — V3 报告章节插件注册表

公开 API:
- SECTIONS: 所有注册的 Section 实例列表
- enabled_sections(): 根据 registry.yaml 过滤后的启用列表
"""
import os
import warnings
from typing import List
from ._base import Section

# 注册表（按 sort_order 排序）
SECTIONS: List[Section] = []

# 延迟导入具体 section（避免循环）
# 注意：5 个具体 section（irm/holders/dividend/board/dragon_market）将在
# Task 1.2 / 2.1-2.4 中逐个实现，本函数在 Phase 2 完成后才会真正被调用。
# 当前为空实现，确保 enabled_sections() 返回空列表，避免循环依赖。
def _register_sections():
    from .irm import IRMSection
    from .holders import HoldersSection
    from .dividend import DividendSection
    from .board import BoardSection
    from .dragon_market import DragonMarketSection
    SECTIONS.extend([
        IRMSection(),
        HoldersSection(),
        DividendSection(),
        BoardSection(),
        DragonMarketSection(),
    ])
    SECTIONS.sort(key=lambda s: s.sort_order)

_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "registry.yaml")

# 诊断告警的稳定标记: 告警文案必带此名, 用户可 grep / 用 filterwarnings 定位
_REGISTRY_WARN_MARK = "registry.yaml"

# disabled_sections 的正确写法。与"实际读到了什么"同框出现, 告警才可行动。
_DISABLED_SCHEMA_EXAMPLE = "disabled_sections: [board, irm]"


def _warn_registry_load(reason: str, detail: str) -> None:
    """把 registry.yaml 的一次加载失败显式告警出去 (调用方仍按 [] 继续跑)。

    文案固定含: 标记名 + 绝对路径 + 失败原因 + 底层异常细节, 让"用户配置没生效"
    这件事可被日志/告警捕获, 而不是无声地回落到"全部 section 启用"。

    stacklevel=4: warnings.warn 以"调用 warn 的那一帧"为 1 级往上数, 实际链路是
    消费者 -> enabled_sections() -> _load_disabled() -> 本函数 -> warnings.warn,
    即 1=本函数, 2=_load_disabled, 3=enabled_sections, 4=消费者。故 4 才真正指向
    enabled_sections() **外部**的调用点所在行; 原先写的 3 只退到 enabled_sections()
    内部 (set(_load_disabled()) 那一行), 无论哪个消费方出错都指向同一行, 定位不到
    调用方。告警内容本身已带完整路径与原因, stacklevel 只负责把"哪一行触发的"这层
    定位补回来。

    已知折中: 绕过 enabled_sections() 直接调 _load_disabled() 时帧少一层, 告警会落在
    该直接调用点 —— 那仍是真实调用者, 可定位, 不算误报。
    """
    warnings.warn(
        f"[sections] {_REGISTRY_WARN_MARK} ({_REGISTRY_PATH}) 加载失败, "
        f"本次按「无灰度配置」处理 (全部 section 启用): {reason} | {detail}",
        stacklevel=4,
    )


def _describe_disabled_value(value) -> str:
    """把读到的 disabled_sections 渲染成一句人话, 供 schema 诊断的 detail 使用。

    只描述"读到了什么", 不做判断 (判断在调用点), 也不抛异常 —— 诊断路径自己绝不能
    变成新的失败点。
    """
    if value is None:
        return "None (显式写成 null)"
    if isinstance(value, str):
        preview = value if len(value) <= 40 else value[:37] + "..."
        return f"str 标量 {preview!r} (标量会被拆成字符集合, 结果一个 section 也关不掉)"
    if isinstance(value, list):
        bad = [f"{item!r} ({type(item).__name__})" for item in value if not isinstance(item, str)]
        shown = ", ".join(bad[:5]) + (f" 等 {len(bad)} 项" if len(bad) > 5 else "")
        return f"list 中的非字符串元素: {shown}"
    if isinstance(value, dict):
        return f"dict 映射 (键: {', '.join(map(str, list(value)[:5]))})"
    return f"{type(value).__name__} 类型"


def _is_disabled_schema(value) -> bool:
    """disabled_sections 是否为合法的 list[str]。

    空列表合法 (等于不关任何 section)。缺省 (key 不存在) 由调用点先行判定, 因为
    "没写这个 key" 与 "写了这个 key 但值为 null" 必须区别对待: 前者是默认配置,
    静默; 后者是显式写了错东西, 要告警。isinstance 已同时排除 None / str / dict /
    标量, 故 None 会落到 schema 校验失败分支, 不被静默吞掉。
    """
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _load_disabled() -> list:
    """从 registry.yaml 读 disabled_sections

    降级语义与改造前完全一致: 任何加载失败都返回 [] (绝不抛异常), 即 5 个 section
    全部启用, 报告生成不受影响。唯一变化是不再静默:

    - registry.yaml 不存在 = 当前默认配置 (仓库尚未落该文件), 继续静默返回 [],
      避免每次跑报告都刷噪声;
    - 文件存在却加载不出时, 五个受控失败点各自发出**原因可区分**的 UserWarning:
        1. `import yaml` 失败 -> 报 "PyYAML 不可用"
        2. open/read 失败     -> 报 "配置文件不可读" (OSError / 解码失败)
        3. safe_load 失败     -> 报 "YAML 解析失败"
        4. 顶层不是映射        -> 报 "YAML 顶层不是 key: value 映射"
        5. disabled_sections 非法 -> 报 "不是字符串列表 (list[str])", 并附实际读到的
           值与正确写法

    第 5 条是**语义**校验而非解析校验: 这类 YAML 完全合法, 但 disabled_sections 写成
    `board` (标量) 时, set() 会把它拆成 {'b','o','a','r','d'} —— 不匹配任何 label,
    于是既没关掉任何 section, 也没有任何告警, 用户以为灰度已生效。故此处强制
    list[str]; 校验不过一律返回 [], 即 5 个 section 全开, 与其余四条降级路径同一
    等待遇, 绝不抛异常打断报告。

    key 缺省与空列表都是合法配置, 静默返回 []; "写了 key 但值是 null" 属于第 5 条
    (显式写错了东西), 告警而不是静默。

    文件内容先整体读出再交给 yaml, 这样"读不到"与"解析不了"能被区分开 (直接传
    文件对象给 safe_load 时, 读错误会被混进解析错误里)。
    """
    if not os.path.exists(_REGISTRY_PATH):
        return []

    try:
        # 延迟导入 yaml (venv 可能未安装 pyyaml)
        import yaml
    except Exception as exc:
        _warn_registry_load("PyYAML 不可用, 无法读取灰度配置", f"{type(exc).__name__}: {exc}")
        return []

    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        _warn_registry_load("配置文件不可读", f"{type(exc).__name__}: {exc}")
        return []

    try:
        cfg = yaml.safe_load(raw) or {}
    except Exception as exc:
        _warn_registry_load("YAML 解析失败", f"{type(exc).__name__}: {exc}")
        return []

    if not isinstance(cfg, dict):
        _warn_registry_load(
            "YAML 顶层不是 key: value 映射",
            f"解析结果类型为 {type(cfg).__name__}",
        )
        return []

    if "disabled_sections" not in cfg:
        return []  # key 缺省 = 无灰度配置, 合法且静默

    disabled = cfg["disabled_sections"]
    if not _is_disabled_schema(disabled):
        _warn_registry_load(
            "disabled_sections 不是字符串列表 (list[str])",
            f"实际读到 {_describe_disabled_value(disabled)}; "
            f"正确写法: {_DISABLED_SCHEMA_EXAMPLE}",
        )
        return []

    return disabled


def enabled_sections() -> List[Section]:
    """返回按 sort_order 排序的启用 section 列表"""
    if not SECTIONS:
        _register_sections()
    disabled = set(_load_disabled())
    return [s for s in SECTIONS if s.label not in disabled]


__all__ = ["Section", "SECTIONS", "enabled_sections"]
