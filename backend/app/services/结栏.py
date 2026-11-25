"""结栏：入栏缓冲按站点+指标汇总物化。

跨站禁混（栏规 禁混汇总）：
- 甲 切流账册拒拼：仅锚站进正式汇总，异站拒进本趟、留在在栏并钉指纹。
- 乙 双写两轨：锚站进正式汇总，异站物化进只读影子归档（命运=影子归档）。
- 关：基线行为不变，全部在栏缓冲直接汇总。
全部写库在站界闸保护的单事务内，同成同败。
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict

from app.db import 连接
from app.seed import 此刻
from app.services import 目录, 站界


def _写正式行(conn, 栏号: str, 站点: str, 指标: str, evs: list, 时刻: str) -> dict:
    均值 = sum(float(e["读数"]) for e in evs) / len(evs)
    编号 = f"汇-{栏号}-{站点}-{指标}-{uuid.uuid4().hex[:6]}"
    conn.execute(
        """INSERT INTO 站点汇总账(汇总编号,栏号,站点键,指标键,报文数,均值,物化时,命运)
           VALUES (?,?,?,?,?,?,?,?)""",
        (编号, 栏号, 站点, 指标, len(evs), 均值, 时刻, 站界.正式命运),
    )
    for e in evs:
        conn.execute(
            "UPDATE 入栏缓冲 SET 命运=? WHERE 报文编号=?",
            (站界.正式命运, e["报文编号"]),
        )
        conn.execute(
            "UPDATE 观测报文 SET 命运=? WHERE 报文编号=?",
            (站界.正式命运, e["报文编号"]),
        )
    return {
        "汇总编号": 编号,
        "站点键": 站点,
        "指标键": 指标,
        "报文数": len(evs),
        "均值": round(均值, 4),
    }


def _写影子行(conn, 栏号: str, 站点: str, 指标: str, evs: list, 时刻: str) -> dict:
    均值 = sum(float(e["读数"]) for e in evs) / len(evs)
    编号 = f"影-{栏号}-{站点}-{指标}-{uuid.uuid4().hex[:6]}"
    # 双写两轨：站点汇总账内留影子命运行，另写影子归档表，正式读只取已汇总命运
    conn.execute(
        """INSERT INTO 站点汇总账(汇总编号,栏号,站点键,指标键,报文数,均值,物化时,命运)
           VALUES (?,?,?,?,?,?,?,?)""",
        (编号, 栏号, 站点, 指标, len(evs), 均值, 时刻, 站界.影子命运),
    )
    conn.execute(
        """INSERT INTO 影子归档(汇总编号,栏号,站点键,指标键,报文数,均值,物化时,命运)
           VALUES (?,?,?,?,?,?,?,?)""",
        (编号, 栏号, 站点, 指标, len(evs), 均值, 时刻, 站界.影子命运),
    )
    for e in evs:
        conn.execute(
            "UPDATE 入栏缓冲 SET 命运=? WHERE 报文编号=?",
            (站界.正式命运, e["报文编号"]),
        )
        conn.execute(
            "UPDATE 观测报文 SET 命运=? WHERE 报文编号=?",
            (站界.正式命运, e["报文编号"]),
        )
    return {
        "汇总编号": 编号,
        "站点键": 站点,
        "指标键": 指标,
        "报文数": len(evs),
        "均值": round(均值, 4),
    }


def 结当前栏() -> dict:
    规 = 目录.栏规()
    栏号 = 规.get("当前栏号", "B-demo")
    批 = f"结栏-{uuid.uuid4().hex[:8]}"
    形态 = 站界.形态(规)
    时刻 = 此刻()
    with 站界.站界闸() as conn:
        rows = conn.execute(
            "SELECT * FROM 入栏缓冲 WHERE 栏号=? AND 命运='在栏'", (栏号,)
        ).fetchall()
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for r in rows:
            groups[(r["站点键"], r["指标键"])].append(r)

        明细: list[dict] = []
        影子明细: list[dict] = []
        拒拼异站: list[str] = []
        影子异站: list[str] = []
        汇总 = 0
        本趟消耗 = 0
        锚 = None

        if 站界.启用(规):
            显式锚 = 站界.锚站(规)
            旧正式 = [
                r["站点键"]
                for r in conn.execute(
                    "SELECT DISTINCT 站点键 FROM 站点汇总账 WHERE 栏号=? AND 命运='已汇总'",
                    (栏号,),
                ).fetchall()
            ]
            if 显式锚:
                锚 = 显式锚
            elif 旧正式:
                锚 = 旧正式[0]  # 同栏锚站粘性：换站撞结栏不得改本站
            else:
                锚 = 站界.选锚站(rows, 规)
            策略名 = 站界.形态名(规)
            for (站点, 指标), evs in sorted(groups.items()):
                if 站点 == 锚:
                    明细.append(_写正式行(conn, 栏号, 站点, 指标, evs, 时刻))
                    汇总 += 1
                    本趟消耗 += len(evs)
                else:
                    for e in evs:
                        站界.钉指纹(
                            conn, 栏号, 锚 or "", 站点, e["报文编号"], 策略名,
                            "拒拼" if 形态 == "甲" else "影子归档",
                        )
                    if 形态 == "甲":
                        # 切流账册：异站拒进本趟，留在在栏缓冲
                        拒拼异站.append(站点)
                    else:
                        # 双写两轨：异站物化进只读影子归档
                        影子明细.append(_写影子行(conn, 栏号, 站点, 指标, evs, 时刻))
                        影子异站.append(站点)
                        本趟消耗 += len(evs)
        else:
            for (站点, 指标), evs in sorted(groups.items()):
                明细.append(_写正式行(conn, 栏号, 站点, 指标, evs, 时刻))
                汇总 += 1
                本趟消耗 += len(evs)

        报告 = {
            "批次编号": 批,
            "栏号": 栏号,
            "汇总数": 汇总,
            "缓冲消耗": 本趟消耗,
            "明细": 明细,
            "空栏": len(rows) == 0,
            "禁混形态": 形态,
            "锚站": 锚,
            "拒拼异站": sorted(set(拒拼异站)),
            "影子异站": sorted(set(影子异站)),
            "影子明细": 影子明细,
        }
        conn.execute(
            """INSERT INTO 结栏批次(编号,栏号,时刻,汇总数,报告) VALUES (?,?,?,?,?)""",
            (批, 栏号, 时刻, 汇总, json.dumps(报告, ensure_ascii=False)),
        )
        conn.commit()
        return 报告


def 预览结栏() -> dict:
    """只读：当前栏在栏缓冲按站点指标分组，不写库；含站界裁决视图。"""
    规 = 目录.栏规()
    栏号 = 规.get("当前栏号", "B-demo")
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT * FROM 入栏缓冲 WHERE 栏号=? AND 命运='在栏'", (栏号,)
        ).fetchall()
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for r in rows:
            groups[(r["站点键"], r["指标键"])].append(dict(r))
        预览 = []
        for (站点, 指标), evs in sorted(groups.items()):
            预览.append({
                "站点键": 站点,
                "指标键": 指标,
                "报文数": len(evs),
                "均值": round(sum(float(e["读数"]) for e in evs) / len(evs), 4),
            })
        锚 = None
        if 站界.启用(规):
            显式锚 = 站界.锚站(规)
            旧正式 = conn.execute(
                "SELECT DISTINCT 站点键 FROM 站点汇总账 WHERE 栏号=? AND 命运='已汇总'",
                (栏号,),
            ).fetchall()
            if 显式锚:
                锚 = 显式锚
            elif 旧正式:
                锚 = 旧正式[0]["站点键"]
            else:
                锚 = 站界.选锚站(rows, 规)
        站点集 = sorted({r["站点键"] for r in rows})
        return {
            "栏号": 栏号,
            "在栏": len(rows),
            "将汇总组": 预览,
            "禁混形态": 站界.形态(规),
            "禁混形态名": 站界.形态名(规),
            "锚站": 锚,
            "站点集": 站点集,
            "含异站片": 锚 is not None and any(s != 锚 for s in 站点集),
        }
    finally:
        conn.close()
