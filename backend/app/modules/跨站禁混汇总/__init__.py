"""跨站禁混汇总（已落子）。

契约：
- 禁止把不同站点报文拼进同一正式汇总行；汇总站点键与缓冲同票。
- 甲 切流账册拒拼：异站拒进本趟汇总并钉指纹，正式汇总只含本站。
- 乙 双写两轨：异站落只读影子归档，现行汇总改读正式集，读引用不同。
- 页面须能读到：当前策略名、命运变化、可点的下一步。
"""
from __future__ import annotations

from app.services import 目录, 站界

NAME = "跨站禁混汇总"
CONTRACT = "禁止把不同站点报文拼进同一汇总行"
HOOKS = ("before_load", "after_load", "decide_gate", "before_close", "after_close", "extra_verify_checks")


def describe() -> dict:
    规 = 目录.栏规()
    形态 = 站界.形态(规)
    return {
        "空桩": NAME,
        "契约": CONTRACT,
        "钩子": list(HOOKS),
        "默认启用": False,
        "已落子": True,
        "当前形态": 形态,
        "形态名": 站界.形态名(规),
        "锚站": 站界.锚站(规),
        "裁决": 站界.读裁决(),
        "可点下一步": [
            "POST /api/站界/换站 切换本站（锚站）",
            "GET /api/站界/裁决 只读站界裁决",
            "GET /api/站界/影子归档 只读异站影子归档",
        ],
    }


def before_load(batch: dict) -> dict:
    return batch


def after_load(report: dict) -> dict:
    return report


def decide_gate(event: dict, rules: dict) -> str:
    return "入栏"


def before_close(pen_id: str) -> None:
    return None


def after_close(report: dict) -> dict:
    return report


def extra_verify_checks(snapshot: dict) -> list[str]:
    """贯验假绿防护：影子归档不得充正式，键须同票。"""
    检查: list[str] = []
    if snapshot.get("影子归档报文", 0) and snapshot.get("汇总报文") is not None:
        检查.append("影子归档报文不计入正式汇总报文数")
    if not snapshot.get("是否对齐", False):
        检查.append(snapshot.get("说明", "栏账撕裂"))
    return 检查
