"""争用失败测：结栏与换站并发，双请求双混则红。

契约（题面）：
- 结栏与换站互斥，并发双请求不得双双成功。
- 无论甲（切流账册）还是乙（双写两轨），混站片都不得进同一正式汇总。
- 读入栏写汇总同成同败：中途失败整笔回滚，不留半截物化。
"""
from __future__ import annotations

import threading

import pytest

from app.services import 装载, 结栏, 目录
from app.services import 站界


def _混站批(前缀: str) -> dict:
    return {
        "批次编号": f"混站-{前缀}",
        "报文": [
            {"报文编号": f"{前缀}-1", "站点键": "站-河东", "指标键": "PM25", "读数": 30.0,
             "观测时": "2026-11-25T12:00:00Z"},
            {"报文编号": f"{前缀}-2", "站点键": "站-河东", "指标键": "PM25", "读数": 32.0,
             "观测时": "2026-11-25T12:10:00Z"},
            {"报文编号": f"{前缀}-3", "站点键": "站-湖西", "指标键": "浊度", "读数": 1.6,
             "观测时": "2026-11-25T12:05:00Z"},
        ],
    }


@pytest.mark.parametrize("策略", ["甲", "乙"])
def test_争_结栏与换站并发只能一个成功(策略):
    目录.改栏规({"禁混汇总": 策略})
    装载.装一批(_混站批(f"Z1{策略}"))

    果: dict = {}

    def 跑结栏() -> None:
        try:
            果["结栏"] = 结栏.结当前栏()
        except Exception as e:  # noqa: BLE001 - 并发断言需要接住异常类型
            果["结栏错"] = e

    def 跑换站() -> None:
        try:
            果["换站"] = 站界.换站("站-北岭")
        except Exception as e:  # noqa: BLE001
            果["换站错"] = e

    t1 = threading.Thread(target=跑结栏)
    t2 = threading.Thread(target=跑换站)
    t1.start(); t2.start()
    t1.join(); t2.join()

    # 缺互斥会双成功——这里必须恰好一边失败
    错 = 果.get("结栏错") or 果.get("换站错")
    assert isinstance(错, 站界.站界占用), f"并发未互斥：{果}"
    assert ("结栏" in 果) != ("换站" in 果)

    # 正式汇总站点集合最多一个站，绝不混站
    正式站点 = {r["站点键"] for r in 目录.汇总列表()}
    assert len(正式站点) <= 1, f"混站片进正式汇总：{正式站点}"


@pytest.mark.parametrize("策略", ["甲", "乙"])
def test_争_双结栏并发不得重复物化(策略):
    目录.改栏规({"禁混汇总": 策略})
    装载.装一批(_混站批(f"Z2{策略}"))

    果: dict = {}

    def 跑(名: str) -> None:
        try:
            果[名] = 结栏.结当前栏()
        except Exception as e:  # noqa: BLE001
            果[f"{名}错"] = e

    t1 = threading.Thread(target=跑, args=("a",))
    t2 = threading.Thread(target=跑, args=("b",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert isinstance(果.get("a错") or 果.get("b错"), 站界.站界占用)
    assert ("a" in 果) != ("b" in 果)

    正式 = 目录.汇总列表()
    assert len(正式) == 1
    assert {r["站点键"] for r in 正式} == {"站-河东"}
    编号 = [r["汇总编号"] for r in 正式]
    assert len(编号) == len(set(编号))

    # 缓冲命运没有被两趟重复消耗
    assert len(目录.缓冲列表("已汇总")) == (2 if 策略 == "甲" else 3)


@pytest.mark.parametrize("策略", ["甲", "乙"])
def test_争_结栏中途失败整笔回滚(策略, monkeypatch):
    目录.改栏规({"禁混汇总": 策略})
    装载.装一批(_混站批(f"Z3{策略}"))

    def _炸(*_a, **_kw):
        raise RuntimeError("注入失败")

    monkeypatch.setattr(站界, "钉指纹", _炸)

    with pytest.raises(RuntimeError):
        结栏.结当前栏()

    # 同成同败：无正式汇总、无结栏批次、缓冲全部仍在栏
    assert 目录.汇总列表() == []
    assert 目录.结栏批次列表() == []
    assert len(目录.缓冲列表("在栏")) == 3


def test_争_换站后结栏以新锚站为本站():
    目录.改栏规({"禁混汇总": "甲"})
    装载.装一批(_混站批("Z4"))
    站界.换站("站-湖西")
    结栏.结当前栏()

    正式 = 目录.汇总列表()
    assert {r["站点键"] for r in 正式} == {"站-湖西"}
    assert {r["报文编号"] for r in 目录.缓冲列表("在栏")} == {"Z4-1", "Z4-2"}


def test_争_换站拒未知站点():
    with pytest.raises(ValueError):
        站界.换站("站-不存在")
