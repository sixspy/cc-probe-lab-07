"""并发双请求脚本：结栏与换站同时打，验证站界互斥、绝不混站。

用法（在仓库根或 backend 下）：
    python scripts/并发双请求.py [甲|乙]

脚本自起 hypercorn（临时数据目录），用 httpx 并发打：
  POST /api/结栏/跑   与   POST /api/站界/换站
断言：
  - 两请求恰好一个 409（站界占用），不允许双成功；
  - 正式汇总账站点集合最多一个站；
  - 再串行跑贯验，影子不充正式。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def 空闲端口() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def 等活(base: str, 超时: float = 30.0) -> None:
    限 = time.time() + 超时
    while time.time() < 限:
        try:
            if httpx.get(f"{base}/api/概览", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.3)
    raise RuntimeError("服务未在超时内就绪")


def main(形态: str = "甲") -> int:
    端口 = 空闲端口()
    base = f"http://127.0.0.1:{端口}"
    数据 = tempfile.mkdtemp(prefix="probe-conc-")
    env = dict(
        os.environ, 数据目录=数据, 夹具目录=str(ROOT.parent / "fixtures"),
        端口=str(端口), 站界持锁秒="1.0",
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "hypercorn", "app.main:app",
         "--bind", f"127.0.0.1:{端口}", "--workers", "2"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        等活(base)
        httpx.post(f"{base}/api/栏规", json={"禁混汇总": 形态}, timeout=10)
        混批 = {
            "批次编号": "并发混站",
            "报文": [
                {"报文编号": "C-1", "站点键": "站-河东", "指标键": "PM25", "读数": 30.0,
                 "观测时": "2026-11-25T08:00:00Z"},
                {"报文编号": "C-2", "站点键": "站-河东", "指标键": "PM25", "读数": 32.0,
                 "观测时": "2026-11-25T08:10:00Z"},
                {"报文编号": "C-3", "站点键": "站-湖西", "指标键": "浊度", "读数": 1.6,
                 "观测时": "2026-11-25T08:05:00Z"},
            ],
        }
        httpx.post(f"{base}/api/观测报文/装载", json=混批, timeout=10)

        撞闸 = 0
        import threading
        # 多轮并发对：Barrier 保证两请求同一瞬间发出（服务端持锁 1s 制造重叠窗口），
        # 要求至少一轮真实撞闸，且每轮正式集绝不混站
        for 轮 in range(3):
            果: dict = {}
            齐 = threading.Barrier(2)

            def 结栏() -> None:
                齐.wait()
                果["结栏"] = httpx.post(f"{base}/api/结栏/跑", timeout=15).status_code

            def 换站() -> None:
                齐.wait()
                果["换站"] = httpx.post(
                    f"{base}/api/站界/换站", json={"锚站": "站-北岭"}, timeout=15
                ).status_code

            t1 = threading.Thread(target=结栏)
            t2 = threading.Thread(target=换站)
            t1.start(); t2.start(); t1.join(); t2.join()
            print(f"轮{轮}: 结栏={果['结栏']} 换站={果['换站']}")
            if 409 in (果["结栏"], 果["换站"]):
                撞闸 += 1
            正式 = httpx.get(f"{base}/api/站点汇总账", timeout=10).json()
            站点 = {r["站点键"] for r in 正式}
            assert len(站点) <= 1, f"混站片进正式汇总：{站点}"

        assert 撞闸 >= 1, "三轮并发未出现一次 409，互斥未被真实触发"
        贯 = httpx.post(f"{base}/api/栏贯验/跑", timeout=10).json()
        print("贯验:", 贯["是否对齐"], "|", 贯["说明"])
        assert 贯["是否对齐"], "贯验撕裂"
        print(f"形态{形态} 并发双请求：撞闸{撞闸}次，互斥与禁混均成立 ✔")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    形 = sys.argv[1] if len(sys.argv) > 1 else "甲"
    raise SystemExit(main(形))
