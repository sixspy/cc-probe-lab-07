"""站界裁决：跨站禁混的工程形态与互斥。

两种工程形态（由栏规 禁混汇总 选择，关=基线不启用）：
- 甲 切流账册拒拼：异站报文拒进本趟正式汇总，留在在栏缓冲，并在站界裁决钉指纹。
- 乙 双写两轨：本站进正式汇总账；异站物化进只读影子归档（站点汇总账内命运=影子归档，
  另写影子归档表），现行正式汇总改读正式集，读引用与归档分离。

约束：
- 汇总站点键与缓冲同票：每个正式汇总行的站点键必须等于其缓冲报文的站点键。
- 结栏与换站互斥：进程内线程闸 + 库内站界锁，缺互斥会双成功（见争用测试）。
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

from app.db import 连接
from app.seed import 此刻

形态表 = {
    "关": "基线不拦",
    "甲": "切流账册拒拼",
    "乙": "双写两轨归档",
}
正式命运 = "已汇总"
影子命运 = "影子归档"
闸名 = "结栏换站闸"

_线程闸 = threading.Lock()


class 站界占用(RuntimeError):
    """结栏与换站并发，另一笔正持站界闸。"""


def 形态(规: dict) -> str:
    return str(规.get("禁混汇总", "关")).strip() or "关"


def 形态名(规: dict) -> str:
    return 形态表.get(形态(规), "基线不拦")


def 启用(规: dict) -> bool:
    return 形态(规) in ("甲", "乙")


def 锚站(规: dict) -> str | None:
    v = str(规.get("锚站") or "").strip()
    return v or None


def 选锚站(rows: list, 规: dict) -> str | None:
    """显式锚站优先；否则取本趟在栏缓冲最先到站的站点（装载顺序即观测入栏顺序）。"""
    显式 = 锚站(规)
    if 显式:
        return 显式
    for r in rows:
        return r["站点键"]
    return None


def 指纹(栏号: str, 锚站: str, 站点: str, 报文编号: str) -> str:
    raw = f"{栏号}|{锚站}|{站点}|{报文编号}"
    return "界-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def 钉指纹(conn, 栏号: str, 锚站: str, 站点: str, 报文编号: str, 策略: str, 裁决: str) -> str:
    印 = 指纹(栏号, 锚站, 站点, 报文编号)
    conn.execute(
        """INSERT OR IGNORE INTO 站界裁决
           (指纹,栏号,锚站,站点键,报文编号,策略,裁决,时刻)
           VALUES (?,?,?,?,?,?,?,?)""",
        (印, 栏号, 锚站, 站点, 报文编号, 策略, 裁决, 此刻()),
    )
    return 印


def 换站(新锚站: str) -> dict:
    """显式换站：与结栏互斥，未知站点拒绝。"""
    from app.services import 目录
    站集合 = {s["源键"] for s in 目录.站点列表()}
    if 新锚站 not in 站集合:
        raise ValueError(f"未知站点：{新锚站}")
    with 站界闸():
        conn = 连接()
        try:
            规 = 目录.栏规()
            旧 = 锚站(规) or ""
            conn.execute(
                "INSERT INTO 栏规(键,值) VALUES (?,?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                ("锚站", 新锚站),
            )
            conn.commit()
            return {"旧锚站": 旧, "锚站": 新锚站, "时刻": 此刻()}
        finally:
            conn.close()


@contextmanager
def 站界闸():
    """进程内非阻塞线程闸 + 库内锁行双保险；持不到闸即抛站界占用。

    业务异常时整笔回滚（同成同败），锁行在独立事务里释放。
    """
    if not _线程闸.acquire(blocking=False):
        raise 站界占用("另一笔结栏/换站正在进行")
    conn = 连接()
    成功 = False
    try:
        try:
            conn.execute(
                "INSERT INTO 站界锁(名,持锁时) VALUES (?,?)", (闸名, 此刻())
            )
            conn.commit()
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            # 锁行已在（主键冲突）或库写锁忙 = 库级互斥失败
            raise 站界占用("站界锁已被占用") from e
        # 仅测试环境变量控制：拉长持锁窗口，便于并发脚本稳定撞闸（生产不设即 0）
        持锁秒 = float(os.environ.get("站界持锁秒", "0") or 0)
        if 持锁秒 > 0:
            time.sleep(持锁秒)
        yield conn
        成功 = True
    finally:
        if not 成功:
            conn.rollback()
        try:
            conn.execute("DELETE FROM 站界锁 WHERE 名=?", (闸名,))
            conn.commit()
        finally:
            conn.close()
            _线程闸.release()


def 读裁决() -> dict:
    """只读：站界裁决台账，正式/异站站点集可区分。

    正式站点集取正式汇总账（命运=已汇总）并上裁决锚站；异站集取裁决站点。
    """
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT * FROM 站界裁决 ORDER BY 时刻"
        ).fetchall()
        正式 = {
            r["站点键"]
            for r in conn.execute(
                "SELECT DISTINCT 站点键 FROM 站点汇总账 WHERE 命运='已汇总'"
            ).fetchall()
        }
        正式.update({r["锚站"] for r in rows if r["锚站"]})
        异站 = sorted({r["站点键"] for r in rows})
        策略 = rows[0]["策略"] if rows else ""
        return {
            "策略": 策略,
            "正式站点集": sorted(正式),
            "异站站点集": 异站,
            "裁决笔数": len(rows),
            "明细": [dict(r) for r in rows],
        }
    finally:
        conn.close()


def 读影子归档() -> list[dict]:
    """只读：异站影子汇总归档，与现行正式汇总账读引用不同。"""
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 影子归档 ORDER BY 物化时 DESC"
            ).fetchall()
        ]
    finally:
        conn.close()
