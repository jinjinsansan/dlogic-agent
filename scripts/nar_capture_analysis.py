#!/usr/bin/env python3
"""NAR の捕捉率 (capture rate) 分析 — 「上位5頭に1-2-3着が入る確率」を直接測る."""
import json, os
from collections import defaultdict, Counter
from datetime import datetime
import psycopg2
from supabase import create_client

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])

NAR_VENUES = {'83':'帯広','30':'門別','35':'盛岡','36':'水沢','45':'浦和','43':'船橋',
              '42':'大井','44':'川崎','46':'金沢','47':'笠松','48':'名古屋','50':'園田',
              '51':'姫路','54':'高知','55':'佐賀'}
NANKAN_CODES = {'42','43','44','45'}
REGION_GROUPS = [{'35','36'},{'46','47','48'},{'50','51'},{'54','55'},{'30','83'}]


def fetch_all(table, select, gte=None, lte=None):
    rows, off = [], 0
    while True:
        q = sb.table(table).select(select)
        if gte:
            for k, v in gte.items(): q = q.gte(k, v)
        if lte:
            for k, v in lte.items(): q = q.lte(k, v)
        res = q.range(off, off+999).execute()
        if not res.data: break
        rows.extend(res.data)
        if len(res.data) < 1000: break
        off += 1000
    return rows


def correct_nar_venue(nen, md, code, schedule):
    if not schedule or 'schedule_data' not in schedule: return code
    days = schedule['schedule_data'].get(nen+md, [])
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


# Load schedule
schedule = None
for p in ['/opt/dlogic/linebot/data/nar_schedule_master_2020_2026.json',
          os.path.join(os.path.dirname(__file__),'..','data','nar_schedule_master_2020_2026.json'),
          r'E:\dev\Cusor\chatbot\uma\backend\data\nar_schedule_master_2020_2026.json']:
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f: schedule = json.load(f)
        break

print('loading clean engine data...')
all_rows = fetch_all('engine_hit_rates','date,race_id,venue,race_number,race_type,engine,top1_horse,top3_horses,created_at',
                    gte={'date':'2025-04-27'}, lte={'date':'2026-04-26'})
clean_by_race = defaultdict(dict)
race_meta = {}
for r in all_rows:
    rd = datetime.strptime(r['date'],'%Y-%m-%d').date()
    cd = datetime.fromisoformat(r['created_at'].replace('Z','+00:00')).date()
    if (cd-rd).days > 0: continue
    rid = r['race_id']
    clean_by_race[rid][r['engine']] = (r['top1_horse'], r['top3_horses'] or [])
    race_meta[rid] = (r['date'], r['venue'], r['race_number'], r['race_type'])
clean_by_race = {rid:e for rid,e in clean_by_race.items() if len(e) >= 3}
print(f'  {len(clean_by_race)} clean races')

print('loading PCKEIBA top3 finishers + popularity...')
conn = psycopg2.connect(host='127.0.0.1', port=5432, database='pckeiba',
                       user='postgres', password='postgres')
cur = conn.cursor("se_cur"); cur.itersize = 50000
cur.execute("SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango, "
            "umaban, tansho_ninkijun, kakutei_chakujun "
            "FROM nvd_se WHERE kaisai_nen >= '2025'")
race_horses = defaultdict(dict)  # (date,venue,rno) -> {horse: {pop,finish}}
for nen, md, code, bango, umaban, ninki, chaku in cur:
    cc = correct_nar_venue(nen, md, code, schedule)
    venue = NAR_VENUES.get(cc)
    if not venue: continue
    try:
        rno = int(bango); h = int(str(umaban).strip()); pop = int(str(ninki).strip()); fin = safe_int(chaku)
    except: continue
    date_str = nen+'-'+md[:2]+'-'+md[2:4]
    race_horses[(date_str, venue, rno)][h] = {'pop':pop,'finish':fin}
cur.close()

# Tansho payouts
cur = conn.cursor()
cur.execute("SELECT kaisai_nen,kaisai_tsukihi,keibajo_code,race_bango,"
            "haraimodoshi_tansho_1a,haraimodoshi_tansho_1b "
            "FROM nvd_hr WHERE kaisai_nen >= '2025'")
tansho = {}
for nen, md, code, bango, ta, tb in cur.fetchall():
    cc = correct_nar_venue(nen, md, code, schedule)
    venue = NAR_VENUES.get(cc)
    if not venue: continue
    try: rno = int(bango)
    except: continue
    w = (ta or '').strip(); p = safe_int(tb)
    if not w or w == '00' or p == 0: continue
    try: winner = int(w)
    except: continue
    date_str = nen+'-'+md[:2]+'-'+md[2:4]
    tansho[(date_str, venue, rno)] = (winner, p)
cur.close(); conn.close()
print(f'  {len(tansho)} NAR races with tansho')

# Compute capture rates
stats_overall = {
    'races': 0,
    'winner_pop1': 0,
    'winner_pop_avg': 0,
    'winner_in_4engT3union': 0,  # 1着が4エンジンtop3unionに含まれる
    'winner_in_2engT3': 0,        # 1着が「少なくとも2エンジンの top3」に含まれる
    'winner_in_3engT3': 0,        # 1着が3エンジン以上のtop3
    'winner_in_4engT3': 0,        # 1着が全4エンジンのtop3
    'winner_in_2engT1': 0,        # 1着が2エンジン以上のtop1合議
    'winner_in_4engT1': 0,        # 1着が4エンジン全部のtop1
    'top2_in_4engT3union': 0,    # 1-2着両方
    'top3_in_4engT3union': 0,    # 1-3着全員
    'avg_top3_union_size': 0,    # 4エンジンtop3 unionの平均頭数 (≈ "上位N頭")
    'tansho_payout_sum': 0,
    'cap2_payout_sum': 0,
    'cap_count': 0,
}
venue_stats = defaultdict(lambda: dict(stats_overall))

for rid, eng_picks in clean_by_race.items():
    date, venue, race_no, race_type = race_meta[rid]
    if race_type != 'nar': continue
    horses = race_horses.get((date, venue, race_no), {})
    tan = tansho.get((date, venue, race_no))
    if not tan or not horses: continue
    winner, win_payout = tan
    # 2着・3着
    sorted_finish = sorted([(h, d['finish']) for h, d in horses.items() if d['finish'] > 0],
                           key=lambda x: x[1])
    if len(sorted_finish) < 3: continue
    top1_finisher = sorted_finish[0][0]
    top2_finisher = sorted_finish[1][0]
    top3_finisher = sorted_finish[2][0]

    # Engine picks
    union_t3 = set()
    counts_t3 = Counter()
    counts_t1 = Counter()
    for engine, (top1, top3) in eng_picks.items():
        for h in (top3 or []):
            if h: union_t3.add(h); counts_t3[h] += 1
        if top1: counts_t1[top1] += 1

    s = stats_overall
    vs = venue_stats[venue]
    for st in [s, vs]:
        st['races'] += 1
        st['avg_top3_union_size'] += len(union_t3)
        # winner pop
        wp = horses.get(winner, {}).get('pop')
        if wp == 1: st['winner_pop1'] += 1
        if wp: st['winner_pop_avg'] += wp
        # capture
        if winner in union_t3: st['winner_in_4engT3union'] += 1
        if counts_t3.get(winner, 0) >= 2: st['winner_in_2engT3'] += 1
        if counts_t3.get(winner, 0) >= 3: st['winner_in_3engT3'] += 1
        if counts_t3.get(winner, 0) >= 4: st['winner_in_4engT3'] += 1
        if counts_t1.get(winner, 0) >= 2: st['winner_in_2engT1'] += 1
        if counts_t1.get(winner, 0) >= 4: st['winner_in_4engT1'] += 1
        if winner in union_t3 and top2_finisher in union_t3:
            st['top2_in_4engT3union'] += 1
        if winner in union_t3 and top2_finisher in union_t3 and top3_finisher in union_t3:
            st['top3_in_4engT3union'] += 1
        if winner in union_t3:
            st['cap_count'] += 1
            st['tansho_payout_sum'] += win_payout

# Render
def pct(num, den):
    return num/den*100 if den else 0

s = stats_overall
n = s['races']
print('\n' + '='*70)
print(f'=== NAR clean データの捕捉率 (n={n} races) ===')
print('='*70)
print(f"\n--- 1着馬の捕捉率 (winner) ---")
print(f"  1着馬が4エンジンtop3 union に入る (≈各エンジン上位3-5頭): {pct(s['winner_in_4engT3union'],n):.1f}% ← ★捕捉率")
print(f"  1着馬が2エンジン以上の top3 に入る:                       {pct(s['winner_in_2engT3'],n):.1f}%")
print(f"  1着馬が3エンジン以上の top3 に入る:                       {pct(s['winner_in_3engT3'],n):.1f}%")
print(f"  1着馬が4エンジン全部の top3 に入る:                       {pct(s['winner_in_4engT3'],n):.1f}%")
print(f"  1着馬が2エンジン以上の top1 合議:                        {pct(s['winner_in_2engT1'],n):.1f}%")
print(f"  1着馬が4エンジン全部の top1 合議:                        {pct(s['winner_in_4engT1'],n):.1f}%")
print(f"\n--- 1-2着・1-3着の同時捕捉 ---")
print(f"  1着&2着 両方が union に入る:        {pct(s['top2_in_4engT3union'],n):.1f}%")
print(f"  1着&2着&3着 全員が union に入る:    {pct(s['top3_in_4engT3union'],n):.1f}%")
print(f"\n--- 平均top3 union サイズ (≈実質「上位N頭」) ---")
print(f"  平均: {s['avg_top3_union_size']/n:.1f}頭/レース  ←「上位5頭」感覚と概ね一致するか")
print(f"\n--- 1人気率と回収 ---")
cap_n = s['cap_count']
print(f"  1着馬が1人気だった割合:        {pct(s['winner_pop1'],n):.1f}% (高いほど本命寄り)")
print(f"  1着馬の平均人気:              {s['winner_pop_avg']/n:.2f}人気")
if cap_n > 0:
    avg_payout_when_cap = s['tansho_payout_sum'] / cap_n
    print(f"  捕捉した時の単勝平均払戻:     ¥{avg_payout_when_cap:.0f} ({avg_payout_when_cap/100*100:.0f}% recovery if 1点買い)")

print(f"\n=== 会場別 1着捕捉率 (top3 union) ===")
print(f"{'会場':<8} {'n':>5} {'cap%':>7} {'1人気%':>7} {'avg_pop':>8} {'平均top3 union':>14}")
for v in sorted(venue_stats.keys()):
    vs = venue_stats[v]
    if vs['races'] < 30: continue
    n2 = vs['races']
    cap = pct(vs['winner_in_4engT3union'], n2)
    pop1 = pct(vs['winner_pop1'], n2)
    avgpop = vs['winner_pop_avg']/n2 if n2 else 0
    avgsize = vs['avg_top3_union_size']/n2 if n2 else 0
    print(f"{v:<8} {n2:>5} {cap:>6.1f}% {pop1:>6.1f}% {avgpop:>7.2f} {avgsize:>13.1f}")
