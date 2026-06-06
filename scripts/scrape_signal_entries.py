#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案B 下準備: JRAシグナル対象レースの出馬表(番号→実馬名)を取得しJSON化。

odds_signals.horse_name は "5番" 等の番号プレースホルダなので、D-Logic採点には
実馬名が要る。netkeiba shutuba を fetch_race_entries で取得して
{race_id: {horse_number: horse_name}} を保存する。

出力: /opt/dlogic/backend/data/signal_entries.json
Usage: python scripts/scrape_signal_entries.py
"""
import json
import os
import sys
import time

sys.path.insert(0, "/opt/dlogic/linebot")

# odds-data プロジェクトの Supabase 認証 (odds-monitor .env)
for line in open("/opt/dlogic/odds-monitor/.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from supabase import create_client
from scrapers.jra import fetch_race_entries

JRA_VENUES = ['東京', '中山', '阪神', '京都', '中京', '新潟', '福島', '小倉', '札幌', '函館']
OUT = "/opt/dlogic/backend/data/signal_entries.json"


def entries_of(detail):
    """RaceDetail から {horse_number: horse_name} を取り出す(構造差異に頑健に)。"""
    out = {}
    ents = getattr(detail, "entries", None) or (detail.get("entries") if isinstance(detail, dict) else None)
    for e in (ents or []):
        hn = getattr(e, "horse_number", None) if not isinstance(e, dict) else e.get("horse_number")
        nm = getattr(e, "horse_name", None) if not isinstance(e, dict) else e.get("horse_name")
        if hn and nm:
            out[int(hn)] = nm
    return out


def main():
    c = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rids, start = set(), 0
    while True:
        r = c.table('odds_signals').select('race_id').in_('venue', JRA_VENUES).range(start, start + 999).execute().data
        rids.update(x['race_id'] for x in r)
        if len(r) < 1000:
            break
        start += 1000
    rids = sorted(rids)
    print(f"対象レース: {len(rids)}")

    # 既存キャッシュは再利用
    out = {}
    if os.path.exists(OUT):
        try:
            out = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            out = {}
    print(f"既存キャッシュ: {len(out)}")

    done = 0
    for i, rid in enumerate(rids):
        if rid in out and out[rid]:
            continue
        try:
            d = fetch_race_entries(rid)
            m = entries_of(d) if d else {}
            if m:
                out[rid] = {str(k): v for k, v in m.items()}
                done += 1
        except Exception as e:
            pass
        if i % 50 == 0:
            print(f"  {i}/{len(rids)}  取得済 {len([1 for v in out.values() if v])}", flush=True)
            json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(0.3)

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"完了: {len([1 for v in out.values() if v])}/{len(rids)} レース -> {OUT}")


if __name__ == '__main__':
    main()
