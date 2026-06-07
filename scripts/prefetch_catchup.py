#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""当日プリフェッチの欠落を朝に自動補完する(JRA/NAR)。

前夜18:00の dlogic-{jra,nar}-prefetch は、netkeibaが翌日のレース一覧をまだ
公開していない時間帯(土深夜など)だと「非開催」と誤判定して失敗し、当日ファイルが
JRA/NAR欠落のまま残る → netkeitaが前日のまま/地方欠落になる。

本スクリプトは朝(netkeiba公開後)に当日ファイルを点検し、JRA/NARが欠けていれば
prefetch_races.py で補完→JRA+NARをマージ→netkeita-api再起動する。
完全なら何もしない(冪等)。systemd timer で race-day 朝に複数回実行する想定。
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
BASE = "/opt/dlogic/linebot"
PREFETCH_DIR = os.path.join(BASE, "data", "prefetch")
PYTHON = os.path.join(BASE, "venv", "bin", "python3")
PREFETCH = os.path.join(BASE, "scripts", "prefetch_races.py")


def load_races(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
        return d.get("races", d) if isinstance(d, dict) else d
    except Exception:
        return []


def run_prefetch(date_str, flag):
    """prefetch_races.py を実行(上書き保存)し、生成された races を返す。失敗時 []。"""
    try:
        subprocess.run([PYTHON, PREFETCH, date_str, flag], cwd=BASE,
                       capture_output=True, text=True, timeout=300)
    except Exception:
        return []
    return load_races(os.path.join(PREFETCH_DIR, f"races_{date_str}.json"))


def main():
    now = datetime.now(JST)
    date_str = now.strftime("%Y%m%d")
    f = os.path.join(PREFETCH_DIR, f"races_{date_str}.json")

    cur = load_races(f)
    jra = [r for r in cur if not r.get("is_local")]
    nar = [r for r in cur if r.get("is_local")]

    changed = False
    if not jra:  # JRA欠落 → 補完
        got = run_prefetch(date_str, "--jra")
        gj = [r for r in got if not r.get("is_local")]
        if gj:
            jra, changed = gj, True
    if not nar:  # NAR欠落 → 補完(prefetch --nar は上書きするので jra はメモリ保持で足し戻す)
        got = run_prefetch(date_str, "--nar")
        gn = [r for r in got if r.get("is_local")]
        if gn:
            nar, changed = gn, True

    if not changed:
        print(f"[{now:%H:%M}] {date_str}: 補完不要 (JRA{len(jra)} NAR{len(nar)})", flush=True)
        return 0

    merged = {
        "metadata": {"date": date_str, "total_races": len(jra) + len(nar),
                     "created_at": now.isoformat()},
        "races": nar + jra,
    }
    tmp = f + ".tmp"
    json.dump(merged, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, f)
    try:
        subprocess.run(["systemctl", "restart", "netkeita-api"], timeout=60)
    except Exception as e:
        print(f"WARN: netkeita-api restart 失敗: {e}", file=sys.stderr)
    print(f"[{now:%H:%M}] {date_str}: 補完完了 JRA{len(jra)} + NAR{len(nar)} → netkeita-api再起動", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
