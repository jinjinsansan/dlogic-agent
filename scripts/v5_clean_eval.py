#!/usr/bin/env python3
"""v5 厳格・高ルールを clean データで再評価."""
import os, json
from collections import defaultdict, Counter
from datetime import datetime
import psycopg2
from supabase import create_client

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])

def fetch_all(table, select, gte=None, lte=None):
    rows, off = [], 0
    while True:
        q = sb.table(table).select(select)
        if gte:
            for k,v in gte.items(): q = q.gte(k,v)
        if lte:
            for k,v in lte.items(): q = q.lte(k,v)
        res = q.range(off, off+999).execute()
        if not res.data: break
        rows.extend(res.data)
        if len(res.data) < 1000: break
        off += 1000
    return rows

print("loading engine_hit_rates clean...")
all_rows = fetch_all('engine_hit_rates', 'date,race_id,venue,race_number,race_type,engine,top1_horse,top3_horses,created_at',
                    gte={'date':'2025-04-27'}, lte={'date':'2026-04-26'})
clean = []
for r in all_rows:
    rd = datetime.strptime(r['date'], '%Y-%m-%d').date()
    cd = datetime.fromisoformat(r['created_at'].replace('Z','+00:00')).date()
    if (cd-rd).days <= 0:
        clean.append(r)
print(f"  {len(clean)} clean rows")

by_race = defaultdict(dict)
race_meta = {}
for r in clean:
    rid = r['race_id']
    by_race[rid][r['engine']] = (r['top1_horse'], r['top3_horses'] or [])
    race_meta[rid] = (r['date'], r['venue'], r['race_number'], r['race_type'])
print(f"  unique races: {len(by_race)}")

NAR_VENUES = {'83':'帯広','30':'門別','35':'盛岡','36':'水沢','45':'浦和','43':'船橋',
              '42':'大井','44':'川崎','46':'金沢','47':'笠松','48':'名古屋','50':'園田',
              '51':'姫路','54':'高知','55':'佐賀'}
NANKAN_CODES = {'42','43','44','45'}
REGION_GROUPS = [{'35','36'},{'46','47','48'},{'50','51'},{'54','55'},{'30','83'}]

schedule = None
for p in ['/opt/dlogic/linebot/data/nar_schedule_master_2020_2026.json',
          'data/nar_schedule_master_2020_2026.json']:
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f: schedule = json.load(f)
        break

def correct_nar_venue(nen, md, code, schedule):
    if not schedule or 'schedule_data' not in schedule: return code
    rd = nen + md
    days = schedule['schedule_data'].get(rd, [])
    if not days: return code
    if len(days) == 1: return days[0]
    if code in days: return code
    if code in NANKAN_CODES:
        n = [c for c in days if c in NANKAN_CODES]
        if len(n) == 1: return n[0]
    for g in REGION_GROUPS:
        if code in g:
            cands = [c for c in days if c in g]
            if len(cands) == 1: return cands[0]
            break
    return code

def safe_int(v):
    if v is None: return 0
    s = str(v).strip()
    try: return int(s) if s else 0
    except: return 0

print("loading PCKEIBA NAR payouts + popularity...")
conn = psycopg2.connect(host='127.0.0.1', port=5432, database='pckeiba',
                       user='postgres', password='postgres')
cur = conn.cursor()
cur.execute("SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango, "
            "haraimodoshi_tansho_1a, haraimodoshi_tansho_1b "
            "FROM nvd_hr WHERE kaisai_nen >= '2025'")

races_pck = {}
for nen, md, code, bango, ta, tb in cur.fetchall():
    cc = correct_nar_venue(nen, md, code, schedule)
    venue = NAR_VENUES.get(cc)
    if not venue: continue
    try: rno = int(bango)
    except: continue
    winner_str = (ta or '').strip()
    payout = safe_int(tb)
    if not winner_str or winner_str == '00' or payout == 0: continue
    try: winner = int(winner_str)
    except: continue
    date_str = nen + '-' + md[:2] + '-' + md[2:4]
    races_pck[(date_str, venue, rno)] = {'winner': winner, 'payout': payout, 'horses': {}}

cur2 = conn.cursor("se_cur"); cur2.itersize = 50000
cur2.execute("SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango, "
             "umaban, tansho_ninkijun "
             "FROM nvd_se WHERE kaisai_nen >= '2025'")
for nen, md, code, bango, umaban, ninki in cur2:
    cc = correct_nar_venue(nen, md, code, schedule)
    venue = NAR_VENUES.get(cc)
    if not venue: continue
    try:
        rno = int(bango)
        h = int(str(umaban).strip())
        pop = int(str(ninki).strip())
    except: continue
    date_str = nen + '-' + md[:2] + '-' + md[2:4]
    race = races_pck.get((date_str, venue, rno))
    if race: race['horses'][h] = pop
cur2.close(); cur.close(); conn.close()
print(f"  loaded {len(races_pck)} NAR races with payouts+pop")

GOLDEN_STRONG_VENUES_V4 = {"川崎", "船橋", "大井", "浦和", "門別", "笠松"}
GOLDEN_SOUTH_NANKAN = {"川崎", "船橋", "大井", "浦和"}

def weekday_of(date_str):
    return datetime.strptime(date_str, '%Y-%m-%d').weekday()

def evaluate(rid, eng_picks):
    date, venue, race_no, race_type = race_meta[rid]
    if race_type != 'nar': return None
    pck = races_pck.get((date, venue, race_no))
    if not pck: return None
    top1_counts = Counter()
    for engine, picks in eng_picks.items():
        top1 = picks[0]
        if top1: top1_counts[top1] += 1
    if not top1_counts: return None
    cons_horse, cons_count = top1_counts.most_common(1)[0]
    if cons_count < 2: return None
    pop = pck['horses'].get(cons_horse)
    weekday = weekday_of(date)
    is_weekday = weekday <= 4
    return {
        'date': date, 'venue': venue, 'race_no': race_no,
        'cons_horse': cons_horse, 'cons_count': cons_count,
        'pop': pop, 'weekday': weekday, 'is_weekday': is_weekday,
        'won': pck['winner'] == cons_horse,
        'payout': pck['payout'] if pck['winner'] == cons_horse else 0,
    }

evaluated = []
for rid, picks in by_race.items():
    e = evaluate(rid, picks)
    if e: evaluated.append(e)
print(f"\n  evaluable NAR races: {len(evaluated)}")

def aggregate(filtered, label):
    n = len(filtered)
    if n == 0: return label + ": 0件"
    inv = n * 100
    pay = sum(r['payout'] for r in filtered)
    hits = sum(1 for r in filtered if r['won'])
    recov = pay/inv*100
    return label + ": n=" + str(n) + " inv=" + format(inv,',') + " pay=" + format(pay,',') + " profit=" + format(pay-inv, '+,') + " hits=" + str(hits) + " hit%=" + format(hits/n*100, '.1f') + " recov=" + format(recov, '.1f') + "%"

base = [r for r in evaluated if 2 <= r['cons_count'] <= 3]
print()
print("=" * 70)
print("=== v5 ルール再評価 (clean 2ヶ月データ, 単勝¥100) ===")
print("=" * 70)
print()
print(aggregate(base, "ベース (NAR + 2-3 top1一致)"))

high = [r for r in base if r['venue'] in GOLDEN_SOUTH_NANKAN and r['is_weekday']]
print(aggregate(high, "v5 高 (NAR + 南関東4 + 2-3一致 + 月-金)"))

strict = [r for r in base if r['venue'] in GOLDEN_STRONG_VENUES_V4 and r['pop'] == 6 and r['is_weekday']]
print(aggregate(strict, "v5 最高 (NAR + 強会場v4 + 6人気 + 2-3一致 + 月-金)"))

print()
print("--- v5 高 (A5) 会場内訳 ---")
for v in sorted(GOLDEN_SOUTH_NANKAN):
    sub = [r for r in high if r['venue'] == v]
    print("  " + aggregate(sub, v))

print()
print("--- v5 最高 (A3) 会場内訳 ---")
for v in sorted(GOLDEN_STRONG_VENUES_V4):
    sub = [r for r in strict if r['venue'] == v]
    print("  " + aggregate(sub, v))

print()
print("--- 人気バケット (v5 高 = 南関東4場 + 月-金) ---")
print("  pop     n   hit%  recov%")
for pop in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]:
    sub = [r for r in high if r['pop'] == pop]
    if not sub: continue
    n = len(sub); hits = sum(1 for r in sub if r['won']); pay = sum(r['payout'] for r in sub)
    print("  " + str(pop) + "    " + str(n).rjust(5) + " " + format(hits/n*100, '5.1f') + "% " + format(pay/(n*100)*100, '6.1f') + "%")

print()
print("--- 全NAR会場 × 2-3一致 単勝 ---")
print("  venue       n   hit%  recov%")
for v in sorted(NAR_VENUES.values()):
    sub = [r for r in base if r['venue'] == v and r['is_weekday']]
    if not sub or len(sub) < 30: continue
    n = len(sub); hits = sum(1 for r in sub if r['won']); pay = sum(r['payout'] for r in sub)
    print("  " + v.ljust(6) + " " + str(n).rjust(5) + " " + format(hits/n*100, '5.1f') + "% " + format(pay/(n*100)*100, '6.1f') + "%")
