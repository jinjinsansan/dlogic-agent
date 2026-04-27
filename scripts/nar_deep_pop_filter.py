#!/usr/bin/env python3
"""NAR 徹底検証 — 中穴フィルタ × 軸流し × 馬券種 × 会場絞り.

戦略マトリクス:
  複勝 / ワイド / 馬連 / 馬単 / 三連複 / 三連単
  × 人気範囲 (1-2 / 3-5 / 3-7 / 5-8 / 5-10 / 6-12 / 全人気)
  × 会場 (全NAR / 高捕捉会場 / 旧強5会場 / 各会場個別)
  × 軸構成 (BOX / 本命軸+流し / 中穴軸+流し)

統計: Bootstrap 95% CI + Mar/Apr stability + 月-金/土日分離
出力: docs/nar_deep_pop_filter_<date>.md
"""
import json
import os
import random
from collections import defaultdict, Counter
from datetime import datetime
from itertools import combinations

import psycopg2
from supabase import create_client

random.seed(42)

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_ROLE_KEY']

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(PROJECT_DIR, "docs")

NAR_VENUES = {'83':'帯広','30':'門別','35':'盛岡','36':'水沢','45':'浦和','43':'船橋',
              '42':'大井','44':'川崎','46':'金沢','47':'笠松','48':'名古屋','50':'園田',
              '51':'姫路','54':'高知','55':'佐賀'}
NANKAN_CODES = {'42','43','44','45'}
REGION_GROUPS = [{'35','36'},{'46','47','48'},{'50','51'},{'54','55'},{'30','83'}]
SCHEDULE_PATHS = [
    '/opt/dlogic/linebot/data/nar_schedule_master_2020_2026.json',
    os.path.join(PROJECT_DIR, 'data', 'nar_schedule_master_2020_2026.json'),
    r'E:\dev\Cusor\chatbot\uma\backend\data\nar_schedule_master_2020_2026.json',
]

# 高捕捉会場 (1着捕捉 >=56%)
HIGH_CAPTURE_VENUES = {'大井', '園田', '笠松', '水沢', '船橋', '門別'}
# 旧4/25 強5会場
OLD_STRONG5 = {'園田', '水沢', '高知', '笠松', '金沢'}


def load_schedule():
    for p in SCHEDULE_PATHS:
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                return json.load(f)
    return None


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


def parse_horses(s):
    s = (s or '').strip()
    if not s or s == '00': return ()
    if len(s) % 2 != 0: return ()
    out = []
    for i in range(0, len(s), 2):
        try: out.append(int(s[i:i+2]))
        except: return ()
    return tuple(out)


def fetch_all(sb, table, select, gte=None, lte=None):
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


def load_clean_engine(sb):
    rows = fetch_all(sb, 'engine_hit_rates',
        'date,race_id,venue,race_number,race_type,engine,top1_horse,top3_horses,created_at',
        gte={'date': '2025-04-27'}, lte={'date': '2026-04-26'})
    by_race = defaultdict(dict)
    race_meta = {}
    for r in rows:
        try:
            rd = datetime.strptime(r['date'], '%Y-%m-%d').date()
            ct = datetime.fromisoformat(r['created_at'].replace('Z', '+00:00'))
            cd = ct.date()
        except: continue
        # Tighter leakage: same-day records created after 09:00 JST are excluded
        if cd > rd: continue
        if cd == rd:
            jst_hour = (ct.hour + 9) % 24
            if jst_hour >= 9: continue
        if r['race_type'] != 'nar': continue
        rid = r['race_id']
        by_race[rid][r['engine']] = (r['top1_horse'], r['top3_horses'] or [])
        race_meta[rid] = (r['date'], r['venue'], r['race_number'], r['race_type'])
    full = {rid: e for rid, e in by_race.items() if len(e) >= 3}
    return full, race_meta


def load_pckeiba_nar(schedule):
    conn = psycopg2.connect(host='127.0.0.1', port=5432, database='pckeiba',
                           user='postgres', password='postgres')
    cur = conn.cursor()
    cur.execute("""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
               haraimodoshi_tansho_1a, haraimodoshi_tansho_1b,
               haraimodoshi_fukusho_1a, haraimodoshi_fukusho_1b,
               haraimodoshi_fukusho_2a, haraimodoshi_fukusho_2b,
               haraimodoshi_fukusho_3a, haraimodoshi_fukusho_3b,
               haraimodoshi_wide_1a, haraimodoshi_wide_1b,
               haraimodoshi_wide_2a, haraimodoshi_wide_2b,
               haraimodoshi_wide_3a, haraimodoshi_wide_3b,
               haraimodoshi_umaren_1a, haraimodoshi_umaren_1b,
               haraimodoshi_sanrenpuku_1a, haraimodoshi_sanrenpuku_1b
        FROM nvd_hr WHERE kaisai_nen >= '2025'
    """)
    races = {}
    for row in cur.fetchall():
        nen, md, code, bango = row[:4]
        venue = NAR_VENUES.get(correct_nar_venue(nen, md, code, schedule))
        if not venue: continue
        try: rno = int(bango)
        except: continue
        wh = parse_horses(row[4]); wp = safe_int(row[5])
        if not wh: continue
        place_p = {}
        for ia, ib in [(6,7),(8,9),(10,11)]:
            hh = parse_horses(row[ia]); pp = safe_int(row[ib])
            if hh and pp > 0: place_p[hh[0]] = pp
        wide_p = {}
        for ia, ib in [(12,13),(14,15),(16,17)]:
            pair = parse_horses(row[ia]); pp = safe_int(row[ib])
            if len(pair) == 2 and pp > 0: wide_p[frozenset(pair)] = pp
        umaren_pair = parse_horses(row[18]); umaren_pay = safe_int(row[19])
        umaren = (frozenset(umaren_pair), umaren_pay) if len(umaren_pair) == 2 and umaren_pay > 0 else None
        spk_t = parse_horses(row[20]); spk_pay = safe_int(row[21])
        sanren = (frozenset(spk_t), spk_pay) if len(spk_t) == 3 and spk_pay > 0 else None
        date_str = nen+'-'+md[:2]+'-'+md[2:4]
        weekday = ['月','火','水','木','金','土','日'][datetime.strptime(nen+md, '%Y%m%d').weekday()]
        is_weekday = weekday in ('月','火','水','木','金')
        races[(date_str, venue, rno)] = {
            'winner': wh[0], 'win_payout': wp,
            'place_payouts': place_p, 'wide_payouts': wide_p,
            'umaren': umaren, 'sanrenpuku': sanren,
            'venue': venue, 'race_no': rno, 'date_str': date_str,
            'weekday': weekday, 'is_weekday': is_weekday,
            'month': date_str[:7],
        }
    cur.close()

    # popularity + finish
    cur = conn.cursor("se_cur"); cur.itersize = 50000
    cur.execute("""SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
                          umaban, tansho_ninkijun, kakutei_chakujun
                   FROM nvd_se WHERE kaisai_nen >= '2025'""")
    for nen, md, code, bango, umaban, ninki, chaku in cur:
        venue = NAR_VENUES.get(correct_nar_venue(nen, md, code, schedule))
        if not venue: continue
        try:
            rno = int(bango); h = int(str(umaban).strip()); pop = int(str(ninki).strip())
        except: continue
        date_str = nen+'-'+md[:2]+'-'+md[2:4]
        race = races.get((date_str, venue, rno))
        if race:
            race.setdefault('horses', {})[h] = {'pop': pop, 'finish': safe_int(chaku)}
    cur.close(); conn.close()
    for race in races.values():
        race['field_size'] = len(race.get('horses', {}))
        # top 3 finishers
        ranked = sorted([(h, d['finish']) for h, d in race.get('horses', {}).items() if d['finish'] > 0],
                       key=lambda x: x[1])
        race['top3_finish'] = [h for h, _ in ranked[:3]]
    return races


def merge(by_race, race_meta, races_pck):
    n = 0
    for rid, eng in by_race.items():
        date, venue, rno, _ = race_meta[rid]
        race = races_pck.get((date, venue, rno))
        if not race: continue
        votes_top3 = Counter()
        votes_top1 = Counter()
        for engine, (t1, t3) in eng.items():
            for h in (t3 or []):
                if h: votes_top3[h] += 1
            if t1: votes_top1[t1] += 1
        race['votes_top3'] = dict(votes_top3)
        race['votes_top1'] = dict(votes_top1)
        race['matched'] = True
        n += 1
    return n


# ============ 戦略生成 ============
def horses_in_pop_range(race, low, high):
    """votes_top3 union のうち 人気 low-high の馬リスト (vote降順, then pop昇順)"""
    horses = race.get('horses', {})
    votes = race.get('votes_top3', {})
    cands = [h for h in votes.keys() if low <= horses.get(h, {}).get('pop', 99) <= high]
    return sorted(cands, key=lambda h: (-votes[h], horses.get(h, {}).get('pop', 99)))


def cons_horse_top1(race, min_count=2):
    votes = race.get('votes_top1', {})
    if not votes: return None
    h, c = max(votes.items(), key=lambda x: x[1])
    return h if c >= min_count else None


def construct_strategies(race):
    """各戦略の bets リスト: (strategy_name, cost, payout)."""
    out = []
    win_p = race['win_payout']
    winner = race['winner']
    place_p = race['place_payouts']
    wide_p = race['wide_payouts']
    umaren = race['umaren']
    sanren = race['sanrenpuku']
    horses = race.get('horses', {})
    top3_finish = race.get('top3_finish', [])
    finish_set = set(top3_finish)

    # === 複勝戦略 ===
    # F-Mid-3-7: top3union 人気3-7位 全部 複勝
    for low, high, label in [(3,5,'_pop3-5'),(3,7,'_pop3-7'),(5,8,'_pop5-8'),(5,10,'_pop5-10'),(6,12,'_pop6-12')]:
        for h in horses_in_pop_range(race, low, high):
            payout = place_p.get(h, 0)
            out.append((f'F-mid{label}_複勝', 100, payout))

    # F-axis-2eng: top1合議 (>=2) の本命の複勝 (baseline)
    axis = cons_horse_top1(race, min_count=2)
    if axis:
        out.append(('F-axis2eng_本命複勝', 100, place_p.get(axis, 0)))
    axis3 = cons_horse_top1(race, min_count=3)
    if axis3:
        out.append(('F-axis3eng_本命複勝', 100, place_p.get(axis3, 0)))
    axis4 = cons_horse_top1(race, min_count=4)
    if axis4:
        out.append(('F-axis4eng_本命複勝', 100, place_p.get(axis4, 0)))

    # === ワイド戦略 ===
    # W-Mid BOX: top3union 人気3-7位 を BOX (2点～10点)
    for low, high, label in [(3,7,'_pop3-7'),(5,10,'_pop5-10')]:
        cands = horses_in_pop_range(race, low, high)
        if 2 <= len(cands) <= 5:
            for c1, c2 in combinations(cands, 2):
                payout = wide_p.get(frozenset({c1, c2}), 0)
                out.append((f'W-mid{label}_BOX', 100, payout))

    # W-Axis: 本命軸 + 中穴流し
    if axis:
        for low, high, label in [(3,7,'_pop3-7'),(5,10,'_pop5-10')]:
            mids = [h for h in horses_in_pop_range(race, low, high) if h != axis]
            for h2 in mids[:3]:  # 流し最大3頭
                payout = wide_p.get(frozenset({axis, h2}), 0)
                out.append((f'W-本命2eng軸_中穴{label}流し', 100, payout))

    if axis3:
        for low, high, label in [(3,7,'_pop3-7'),(5,10,'_pop5-10')]:
            mids = [h for h in horses_in_pop_range(race, low, high) if h != axis3]
            for h2 in mids[:3]:
                payout = wide_p.get(frozenset({axis3, h2}), 0)
                out.append((f'W-本命3eng軸_中穴{label}流し', 100, payout))

    # === 馬連戦略 ===
    if umaren:
        umaren_pair, umaren_pay = umaren
        # U-Mid BOX
        for low, high, label in [(3,7,'_pop3-7'),(5,10,'_pop5-10')]:
            cands = horses_in_pop_range(race, low, high)
            if 2 <= len(cands) <= 4:
                for c1, c2 in combinations(cands, 2):
                    p = umaren_pay if frozenset({c1,c2}) == umaren_pair else 0
                    out.append((f'U-mid{label}_BOX', 100, p))
        # U-Axis
        for axis_h, axis_label in [(axis,'2eng'),(axis3,'3eng')]:
            if not axis_h: continue
            for low, high, label in [(3,7,'_pop3-7'),(5,10,'_pop5-10')]:
                mids = [h for h in horses_in_pop_range(race, low, high) if h != axis_h]
                for h2 in mids[:3]:
                    p = umaren_pay if frozenset({axis_h, h2}) == umaren_pair else 0
                    out.append((f'U-本命{axis_label}軸_中穴{label}流し', 100, p))

    # === 三連複戦略 ===
    if sanren:
        sp_set, sp_pay = sanren
        # S-Mid BOX
        for low, high, label in [(3,7,'_pop3-7'),(5,10,'_pop5-10')]:
            cands = horses_in_pop_range(race, low, high)
            if 3 <= len(cands) <= 5:
                for combo in combinations(cands, 3):
                    p = sp_pay if frozenset(combo) == sp_set else 0
                    out.append((f'S-mid{label}_BOX', 100, p))
        # S-Axis: 本命軸 + 中穴2頭流し
        for axis_h, axis_label in [(axis,'2eng'),(axis3,'3eng'),(axis4,'4eng')]:
            if not axis_h: continue
            for low, high, label in [(3,7,'_pop3-7'),(5,10,'_pop5-10')]:
                mids = [h for h in horses_in_pop_range(race, low, high) if h != axis_h]
                if len(mids) < 2: continue
                for combo in combinations(mids[:4], 2):
                    p = sp_pay if frozenset({axis_h, *combo}) == sp_set else 0
                    out.append((f'S-本命{axis_label}軸_中穴{label}2頭流し', 100, p))
        # S-AllUnion BOX (top3unionのBOX、サイズ比較用)
        union_horses = list(race.get('votes_top3', {}).keys())
        if 3 <= len(union_horses) <= 5:
            for combo in combinations(union_horses, 3):
                p = sp_pay if frozenset(combo) == sp_set else 0
                out.append(('S-union全BOX', 100, p))

    # === v3 オリジナル仮説 ===
    # 4/25 audit conclusion: 火水木 + 6-12頭 + 5-8人気 + 強5会場 + 2-3一致
    is_v3 = (race['weekday'] in ('火','水','木')
             and 6 <= race.get('field_size', 0) <= 12
             and race['venue'] in OLD_STRONG5)
    if is_v3 and axis:
        ap = horses.get(axis, {}).get('pop', 99)
        if 5 <= ap <= 8:
            out.append(('Z-v3仮説_本命2eng合議単勝', 100, win_p if axis == winner else 0))
            out.append(('Z-v3仮説_本命2eng合議複勝', 100, place_p.get(axis, 0)))

    return out


# ============ aggregate ============
def run_aggregate(races, segment_func):
    results = defaultdict(lambda: defaultdict(lambda: {
        'n': 0, 'invest': 0, 'payout': 0, 'hits': 0, 'samples': []
    }))
    for race in races:
        if not race.get('matched'): continue
        bets = construct_strategies(race)
        if not bets: continue
        segs = segment_func(race)
        for strat, cost, payout in bets:
            for seg in segs:
                s = results[strat][seg]
                s['n'] += 1
                s['invest'] += cost
                s['payout'] += payout
                if payout > 0: s['hits'] += 1
                if seg.startswith('ALL') or seg.startswith('VENUE_GROUP') or seg.startswith('VEN='):
                    s['samples'].append(payout - cost)
    return results


def bootstrap_ci(profits, n_resamples=1000, ci=0.95):
    if not profits or len(profits) < 30: return None, None
    means = []
    n = len(profits)
    for _ in range(n_resamples):
        sample = [profits[random.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(n_resamples * (1 - ci) / 2)]
    hi = means[int(n_resamples * (1 + ci) / 2)]
    return (1 + lo / 100) * 100, (1 + hi / 100) * 100


# ============ render ============
def render_report(results_all, results_month, output_path):
    lines = [
        '# NAR 徹底検証 — 中穴フィルタ × 軸流し × 馬券種クロス\n',
        f'**生成**: {datetime.now().strftime("%Y-%m-%d %H:%M")}\n',
        '**手法**: 強化leakage除去 (同日09:00 JST前のみ採用) + Bootstrap 95% CI + Mar/Apr stability\n',
        '**期間**: 2026-03 ~ 2026-04 (clean 2ヶ月)\n',
        '\n## 統計上の注意\n',
        '- 多数の戦略×セグメントを同一データで検定 → **多重比較問題あり**\n',
        '- Bonferroni目安: 100検定なら有効α≈0.0005。S/A級は発見フェーズ候補として扱うこと。\n',
        '- 2ヶ月データのみ → 季節性・偶発ヒットの排除困難。独立OOSデータでの再検証を推奨。\n',
        '\n## 戦略一覧 (全て NAR 単独)\n',
        '- F-mid_pop{X-Y}_複勝: 4エンジン top3 union のうち人気X-Y位の馬を全部 複勝買い\n',
        '- F-axis{N}eng_本命複勝: Nエンジン以上 top1合議の馬を複勝買い (baseline)\n',
        '- W-mid_pop{X-Y}_BOX: 同範囲の馬で ワイド BOX\n',
        '- W-本命{N}eng軸_中穴{X-Y}流し: 本命軸×中穴流し\n',
        '- U-* / S-*: 馬連 / 三連複 同様\n',
        '- Z-v3仮説: 4/25旧仮説 (火水木+6-12頭+5-8人気+強5会場+2eng合議)\n',
        '\n---\n\n',
    ]

    # Production-ready evaluation
    candidates = []
    for strat, segs in results_all.items():
        for seg, d in segs.items():
            if d['n'] < 50: continue
            if d['invest'] == 0: continue
            recov = d['payout'] / d['invest'] * 100
            ci_lo, ci_hi = bootstrap_ci(d['samples']) if d['samples'] else (None, None)
            mar_d = results_month.get(strat, {}).get(seg + '|2026-03', {'n':0,'invest':0,'payout':0})
            apr_d = results_month.get(strat, {}).get(seg + '|2026-04', {'n':0,'invest':0,'payout':0})
            mar_recov = mar_d['payout']/mar_d['invest']*100 if mar_d['invest'] else 0
            apr_recov = apr_d['payout']/apr_d['invest']*100 if apr_d['invest'] else 0

            ready = '❌'
            if d['n'] >= 100 and ci_lo is not None and ci_lo >= 110 and mar_recov >= 100 and apr_recov >= 100:
                ready = '🌟 S'
            elif d['n'] >= 80 and recov >= 130 and mar_recov >= 90 and apr_recov >= 90:
                ready = '✅ A'
            elif d['n'] >= 50 and recov >= 110:
                ready = '🟡 B'

            candidates.append({
                'strat': strat, 'seg': seg, 'n': d['n'], 'hits': d['hits'],
                'recov': recov, 'ci_lo': ci_lo, 'ci_hi': ci_hi,
                'mar_n': mar_d['n'], 'mar_recov': mar_recov,
                'apr_n': apr_d['n'], 'apr_recov': apr_recov,
                'ready': ready,
            })

    s_tier = [c for c in candidates if c['ready'].startswith('🌟')]
    a_tier = [c for c in candidates if c['ready'].startswith('✅')]
    b_tier = [c for c in candidates if c['ready'].startswith('🟡')]

    lines.append('# 🌟 NAR S級 — Production Ready (n>=100, CI下限>=110%, Mar+Apr両方>=100%)\n\n')
    if s_tier:
        s_tier.sort(key=lambda x: -x['recov'])
        lines.append('| 戦略 | セグメント | n | 回収率 | CI下限 | CI上限 | Mar回収 | Apr回収 |\n|---|---|---:|---:|---:|---:|---:|---:|\n')
        for c in s_tier:
            lines.append(f"| {c['strat']} | {c['seg']} | {c['n']:,} | **{c['recov']:.1f}%** | "
                         f"{c['ci_lo']:.1f}% | {c['ci_hi']:.1f}% | {c['mar_recov']:.1f}% | {c['apr_recov']:.1f}% |\n")
    else:
        lines.append('**該当なし** — clean データだけでは S級認定可能な NAR pattern は無し。\n\n')

    lines.append('\n# ✅ NAR A級 — 有望候補 (n>=80, recov>=130%, Mar+Apr両方>=90%)\n\n')
    a_tier.sort(key=lambda x: -x['recov'])
    if a_tier:
        lines.append('| 戦略 | セグメント | n | 回収率 | CI下限 | Mar回収 | Apr回収 |\n|---|---|---:|---:|---:|---:|---:|\n')
        for c in a_tier[:40]:
            ci = f"{c['ci_lo']:.1f}%" if c['ci_lo'] is not None else 'N/A'
            lines.append(f"| {c['strat']} | {c['seg']} | {c['n']:,} | **{c['recov']:.1f}%** | "
                         f"{ci} | {c['mar_recov']:.1f}% | {c['apr_recov']:.1f}% |\n")
    else:
        lines.append('該当なし\n\n')

    lines.append('\n# 🟡 NAR B級 — 観察対象 (n>=50, recov>=110%)\n\n')
    b_tier.sort(key=lambda x: -x['recov'])
    if b_tier:
        lines.append('| 戦略 | セグメント | n | 回収率 | Mar回収 | Apr回収 |\n|---|---|---:|---:|---:|---:|\n')
        for c in b_tier[:60]:
            lines.append(f"| {c['strat']} | {c['seg']} | {c['n']:,} | {c['recov']:.1f}% | "
                         f"{c['mar_recov']:.1f}% | {c['apr_recov']:.1f}% |\n")

    # 全戦略 サマリ (ALL=all)
    lines.append('\n\n# 全戦略 全NAR サマリ\n\n')
    lines.append('| 戦略 | n | 回収率 | CI下限 | CI上限 |\n|---|---:|---:|---:|---:|\n')
    for strat in sorted(results_all.keys()):
        d = results_all[strat].get('ALL=all', {})
        if not d.get('n'): continue
        recov = d['payout']/d['invest']*100 if d['invest'] else 0
        ci_lo, ci_hi = bootstrap_ci(d.get('samples', []))
        ci_lo_s = f'{ci_lo:.1f}%' if ci_lo is not None else 'N/A'
        ci_hi_s = f'{ci_hi:.1f}%' if ci_hi is not None else 'N/A'
        lines.append(f"| {strat} | {d['n']:,} | {recov:.1f}% | {ci_lo_s} | {ci_hi_s} |\n")

    # 会場グループ別サマリ
    lines.append('\n\n# 会場グループ別 全戦略マトリクス (回収率)\n\n')
    groups = ['ALL=all', 'GRP=high_capture', 'GRP=old_strong5']
    lines.append('| 戦略 | 全NAR | 高捕捉6会場 | 旧強5会場 |\n|---|---:|---:|---:|\n')
    for strat in sorted(results_all.keys()):
        row = [strat]
        for g in groups:
            d = results_all[strat].get(g, {})
            if not d.get('n'):
                row.append('—')
            else:
                recov = d['payout']/d['invest']*100 if d['invest'] else 0
                row.append(f"{recov:.1f}% (n={d['n']:,})")
        lines.append('| ' + ' | '.join(row) + ' |\n')

    # 全候補ランキング
    lines.append('\n\n# 全候補ランキング (n>=50, 回収率順)\n\n')
    all_cands = sorted([c for c in candidates if c['n'] >= 50], key=lambda x: -x['recov'])
    lines.append('| Rank | 戦略 | セグメント | n | 回収率 | Mar | Apr | rating |\n|---|---|---|---:|---:|---:|---:|---|\n')
    for i, c in enumerate(all_cands[:80], 1):
        lines.append(f"| {i} | {c['strat']} | {c['seg']} | {c['n']:,} | **{c['recov']:.1f}%** | "
                     f"{c['mar_recov']:.1f}% | {c['apr_recov']:.1f}% | {c['ready']} |\n")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f'report → {output_path}')


def main():
    print('loading clean engine data (NAR only)...')
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    by_race, race_meta = load_clean_engine(sb)
    print(f'  {len(by_race)} clean NAR races')

    schedule = load_schedule()
    print('loading PCKEIBA NAR full payouts + popularity...')
    races_pck = load_pckeiba_nar(schedule)
    print(f'  {len(races_pck)} PCKEIBA races')

    matched = merge(by_race, race_meta, races_pck)
    print(f'  matched: {matched}')

    races_list = [r for r in races_pck.values() if r.get('matched')]

    def seg(race):
        v = race['venue']
        wd = race['weekday']
        is_wkd = race['is_weekday']
        out = ['ALL=all', f'VEN={v}', f'WD={wd}', f'WKD={"weekday" if is_wkd else "weekend"}']
        if v in HIGH_CAPTURE_VENUES:
            out.append('GRP=high_capture')
            if is_wkd: out.append('GRP=high_capture_weekday')
        if v in OLD_STRONG5:
            out.append('GRP=old_strong5')
            if is_wkd: out.append('GRP=old_strong5_weekday')
        return out

    def seg_month(race):
        m = race['month']
        return [s + f'|{m}' for s in seg(race)]

    print('aggregating overall...')
    res_all = run_aggregate(races_list, seg)
    print('aggregating by month...')
    res_month = run_aggregate(races_list, seg_month)

    out = os.path.join(DOCS_DIR, f'nar_deep_pop_filter_{datetime.now().strftime("%Y%m%d")}.md')
    render_report(res_all, res_month, out)


if __name__ == '__main__':
    main()
