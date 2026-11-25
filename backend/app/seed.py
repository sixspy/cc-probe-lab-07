from datetime import datetime, timezone
import sqlite3
import time

from app.db import 连接, 开wal

建表 = """
CREATE TABLE IF NOT EXISTS 栏规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 站点源 (
  源键 TEXT PRIMARY KEY,
  名称 TEXT NOT NULL,
  介质 TEXT NOT NULL DEFAULT '大气',
  区域 TEXT NOT NULL DEFAULT '',
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 观测报文 (
  报文编号 TEXT PRIMARY KEY,
  站点键 TEXT NOT NULL,
  指标键 TEXT NOT NULL,
  读数 REAL NOT NULL,
  观测时 TEXT NOT NULL,
  处理时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '已装载',
  批次编号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 入栏缓冲 (
  报文编号 TEXT PRIMARY KEY,
  站点键 TEXT NOT NULL,
  指标键 TEXT NOT NULL,
  读数 REAL NOT NULL,
  观测时 TEXT NOT NULL,
  栏号 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '在栏',
  入栏时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 站点汇总账 (
  汇总编号 TEXT PRIMARY KEY,
  栏号 TEXT NOT NULL,
  站点键 TEXT NOT NULL,
  指标键 TEXT NOT NULL,
  报文数 INTEGER NOT NULL,
  均值 REAL NOT NULL,
  物化时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '已汇总'
);
CREATE TABLE IF NOT EXISTS 坏点匣 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  报文编号 TEXT NOT NULL,
  站点键 TEXT NOT NULL,
  原因 TEXT NOT NULL,
  读数 REAL NOT NULL,
  观测时 TEXT NOT NULL,
  入匣时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 栏贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  在栏笔数 INTEGER NOT NULL,
  汇总报文数 INTEGER NOT NULL,
  坏点笔数 INTEGER NOT NULL,
  影子归档报文 INTEGER NOT NULL DEFAULT 0,
  是否对齐 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  入流 INTEGER NOT NULL DEFAULT 0,
  入栏 INTEGER NOT NULL DEFAULT 0,
  坏点 INTEGER NOT NULL DEFAULT 0,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 结栏批次 (
  编号 TEXT PRIMARY KEY,
  栏号 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  汇总数 INTEGER NOT NULL DEFAULT 0,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 站界裁决 (
  指纹 TEXT PRIMARY KEY,
  栏号 TEXT NOT NULL,
  锚站 TEXT NOT NULL,
  站点键 TEXT NOT NULL,
  报文编号 TEXT NOT NULL,
  策略 TEXT NOT NULL,
  裁决 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 影子归档 (
  汇总编号 TEXT PRIMARY KEY,
  栏号 TEXT NOT NULL,
  站点键 TEXT NOT NULL,
  指标键 TEXT NOT NULL,
  报文数 INTEGER NOT NULL,
  均值 REAL NOT NULL,
  物化时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '影子归档'
);
CREATE TABLE IF NOT EXISTS 站界锁 (
  名 TEXT PRIMARY KEY,
  持锁时 TEXT NOT NULL
);
"""


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 初始化库() -> None:
    # 多 worker 可能同时启动：WAL 后对建表/迁移做有限重试
    开wal()
    最后错: Exception | None = None
    for _ in range(10):
        conn = 连接()
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.executescript(建表)
            _播种(conn)
            conn.commit()
            conn.close()
            return
        except sqlite3.OperationalError as e:  # database is locked，等另一 worker 建完
            最后错 = e
            conn.close()
            time.sleep(0.5)
    raise 最后错  # type: ignore[misc]


def _播种(conn) -> None:
    if conn.execute("SELECT COUNT(*) AS c FROM 栏规").fetchone()["c"] == 0:
        for k, v in {
            "当前栏号": "B-demo",
            "PM25上限": "75",
            "PM25下限": "0",
            "标定偏移上限": "5",
            "栏策略": "按站点指标汇总均值",
        }.items():
            conn.execute("INSERT INTO 栏规(键,值) VALUES (?,?)", (k, v))
    # 老库迁移：禁混默认关闭，保持基线 happy path
    if not conn.execute("SELECT 1 FROM 栏规 WHERE 键='禁混汇总'").fetchone():
        conn.execute("INSERT INTO 栏规(键,值) VALUES (?,?)", ("禁混汇总", "关"))
    # 老库迁移：栏贯验增加影子归档报文列
    列 = {r["name"] for r in conn.execute("PRAGMA table_info(栏贯验)").fetchall()}
    if "影子归档报文" not in 列:
        conn.execute("ALTER TABLE 栏贯验 ADD COLUMN 影子归档报文 INTEGER NOT NULL DEFAULT 0")
    if conn.execute("SELECT COUNT(*) AS c FROM 站点源").fetchone()["c"] == 0:
        for row in [
            ("站-河东", "河东大气站", "大气", "城区", "示范站"),
            ("站-湖西", "湖西水质站", "水质", "湖区", "示范站"),
            ("站-北岭", "北岭大气站", "大气", "近郊", "示范站"),
            ("站-江口", "江口大气站", "大气", "河口", "示范站"),
            ("站-林场", "林场微站", "大气", "林区", "示范站"),
        ]:
            conn.execute(
                "INSERT INTO 站点源(源键,名称,介质,区域,说明) VALUES (?,?,?,?,?)",
                row,
            )
