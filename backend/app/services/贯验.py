"""栏贯验：已汇总缓冲报文数 == 正式汇总账报文数之和。

跨站禁混下的防假绿：
- 影子归档（命运=影子归档）不算正式汇总报文，避免混站影子汇总被误标对齐。
- 每站物化总数（正式+影子）须等于该站已汇总缓冲数，漏写/重写即撕裂。
- 影子归档表与站点汇总账影子行逐笔对得上，防止只改一处的假绿。
"""
from __future__ import annotations

from app.db import 连接
from app.seed import 此刻


def _查(conn) -> dict:
    在栏 = conn.execute(
        "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='在栏'"
    ).fetchone()["c"]
    已汇总缓冲 = conn.execute(
        "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='已汇总'"
    ).fetchone()["c"]
    正式报文 = conn.execute(
        "SELECT COALESCE(SUM(报文数),0) AS c FROM 站点汇总账 WHERE 命运='已汇总'"
    ).fetchone()["c"]
    影子报文 = conn.execute(
        "SELECT COALESCE(SUM(报文数),0) AS c FROM 站点汇总账 WHERE 命运='影子归档'"
    ).fetchone()["c"]
    归档影子 = conn.execute(
        "SELECT COALESCE(SUM(报文数),0) AS c FROM 影子归档"
    ).fetchone()["c"]
    坏点 = conn.execute("SELECT COUNT(*) AS c FROM 坏点匣").fetchone()["c"]

    撕裂: list[str] = []
    if int(已汇总缓冲) != int(正式报文) + int(影子报文):
        撕裂.append(
            f"物化总数撕裂：已汇总缓冲={已汇总缓冲} "
            f"正式={正式报文}+影子={影子报文}"
        )
    if int(影子报文) != int(归档影子):
        撕裂.append(
            f"影子归档撕裂：汇总账影子={影子报文} 归档表={归档影子}"
        )

    按站缓冲 = {
        r["站点键"]: r["c"]
        for r in conn.execute(
            "SELECT 站点键,COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='已汇总' GROUP BY 站点键"
        ).fetchall()
    }
    按站物化: dict[str, int] = {}
    for r in conn.execute(
        "SELECT 站点键,COALESCE(SUM(报文数),0) AS c FROM 站点汇总账 GROUP BY 站点键"
    ).fetchall():
        按站物化[r["站点键"]] = r["c"]
    for 站点, c in 按站缓冲.items():
        if 按站物化.get(站点, 0) != c:
            撕裂.append(f"站点{站点}键不同票：缓冲={c} 物化={按站物化.get(站点, 0)}")

    对齐 = not 撕裂
    说明 = (
        "入栏已汇总与站点汇总（正式+影子归档）逐站对齐，影子未充正式"
        if 对齐
        else "；".join(撕裂)
    )
    return {
        "在栏": 在栏,
        "已汇总缓冲": int(已汇总缓冲),
        "汇总报文": int(正式报文),
        "影子归档报文": int(影子报文),
        "坏点": 坏点,
        "是否对齐": 对齐,
        "说明": 说明,
    }


def 跑一次() -> dict:
    conn = 连接()
    try:
        d = _查(conn)
        时刻 = 此刻()
        conn.execute(
            """INSERT INTO 栏贯验(时刻,在栏笔数,汇总报文数,坏点笔数,影子归档报文,是否对齐,说明)
               VALUES (?,?,?,?,?,?,?)""",
            (时刻, d["在栏"], d["汇总报文"], d["坏点"], d["影子归档报文"],
             1 if d["是否对齐"] else 0, d["说明"]),
        )
        conn.commit()
        d["时刻"] = 时刻
        return d
    finally:
        conn.close()


def 只读快照() -> dict:
    """不落库的贯验快照，供页面预览。"""
    conn = 连接()
    try:
        return _查(conn)
    finally:
        conn.close()
