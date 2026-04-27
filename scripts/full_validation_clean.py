#!/usr/bin/env python3
"""完全検証 — clean データ (2026-03~04) で全戦略を多軸検証.

戦略: 単勝・複勝・ワイド・馬連・馬単・三連複・三連単 × 多種コンセンサス
フィルタ: race_type × venue × weekday × pop × month
統計: Bootstrap 95% CI / Mar vs Apr split / production-ready flag

出力: docs/full_validation_clean_<date>.md
"""
import json
import os
import random
from collections import defaultdict, Counter
from datetime import datetime
from itertools import combinations, permutations

import psycopg2
from supabase import create_client

random.seed(42)

# --- env ---
SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_ROLE_KEY']

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(PROJECT_DIR, "docs")

NAR_VENUES = {'83':'帯広','30':'門別','35':'盛岡','36':'水沢','45':'浦和','43':'船橋',
              '42':'大井','44':'川崎','46':'金沢','47':'笠松','48':'名古屋','50':'園田',
              '51':'姫路','54':'高知','55':'佐賀'}
JRA_VENUES = {'01':'札幌','02':'函館','03':'福島','04':'新潟','05':'東京','06':'中山',
              '07':'中京','08':'京都','09':'阪神','10':'小倉'}
NANKAN_CODES = {'42','43','44','45'}
REGION_GROUPS = [{'35','36'},{'46','47','48'},{'50','51'},{'54','55'},{'30','83'}]
SCHEDULE_PATHS = [
    '/opt/dlogic/linebot/data/nar_schedule_master_2020_2026.json',
    os.path.join(PROJECT_DIR, 'data', 'nar_schedule_master_2020_2026.json'),
    r'E:\dev\Cusor\chatbot\uma\backend\data\nar_schedule_master_2020_2026.json',
]


def load_schedule():
    for p in SCHEDULE_PATHS:
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                return json.load(f)
    return None


def correct_nar_venue(nen, md, code, schedule):
    if not schedule or 'schedule_data' not in schedule: return code
    days = schedule['schedule_data'].get(nen + md, [])
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


# --- load engine_hit_rates clean ---
def load_clean_engine(sb):
    rows, off = [], 0
    while True:
        res = sb.table('engine_hit_rates').select(
            'date,race_id,venue,race_number,race_type,engine,top1_horse,top3_horses,created_at'
        ).gte('date', '2025-04-27').lte('date', '2026-04-26').range(off, off+999).execute()
        if not res.data: break
        rows.extend(res.data)
        if len(res.data) < 1000: break
        off += 1000

    by_race = defaultdict(dict)
    race_meta = {}
    for r in rows:
        try:
            rd = datetime.strptime(r['date'], '%Y-%m-%d').date()
            ct = datetime.fromisoformat(r['created_at'].replace('Z', '+00:00'))
            cd = ct.date()
        except (ValueError, TypeError):
            continue
        # Leakage filter: created_at must be strictly before race_date, OR
        # if same day, must be before 09:00 JST (pre-race morning cutoff).
        # This excludes same-day post-race backfill records.
        if cd > rd:
            continue
        if cd == rd:
            # Convert to JST hour
            jst_hour = (ct.hour + 9) % 24
            if jst_hour >= 9:
                continue  # same-day after 9AM JST: likely post-race contamination
        rid = r['race_id']
        by_race[rid][r['engine']] = (r['top1_horse'], r['top3_horses'] or [])
        race_meta[rid] = (r['date'], r['venue'], r['race_number'], r['race_type'])
    full = {rid: e for rid, e in by_race.items() if len(e) >= 3}
    return full, race_meta


# --- load PCKEIBA all bet types ---
def load_pckeiba(table_se, table_hr, race_type, schedule):
    conn = psycopg2.connect(host='127.0.0.1', port=5432, database='pckeiba',
                           user='postgres', password='postgres')
    cur = conn.cursor()
    cur.execute(f"""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
               haraimodoshi_tansho_1a, haraimodoshi_tansho_1b,
               haraimodoshi_fukusho_1a, haraimodoshi_fukusho_1b,
               haraimodoshi_fukusho_2a, haraimodoshi_fukusho_2b,
               haraimodoshi_fukusho_3a, haraimodoshi_fukusho_3b,
               haraimodoshi_wide_1a, haraimodoshi_wide_1b,
               haraimodoshi_wide_2a, haraimodoshi_wide_2b,
               haraimodoshi_wide_3a, haraimodoshi_wide_3b,
               haraimodoshi_umaren_1a, haraimodoshi_umaren_1b,
               haraimodoshi_umatan_1a, haraimodoshi_umatan_1b,
               haraimodoshi_sanrenpuku_1a, haraimodoshi_sanrenpuku_1b,
               haraimodoshi_sanrentan_1a, haraimodoshi_sanrentan_1b
        FROM {table_hr}
        WHERE kaisai_nen >= '2025'
    """)
    races = {}
    for row in cur.fetchall():
        nen, md, code, bango = row[0], row[1], row[2], row[3]
        if race_type == 'jra':
            venue = JRA_VENUES.get(code)
        else:
            venue = NAR_VENUES.get(correct_nar_venue(nen, md, code, schedule))
        if not venue: continue
        try: rno = int(bango)
        except: continue

        winner_h = parse_horses(row[4])
        winner_p = safe_int(row[5])
        if not winner_h: continue

        place_payouts = {}
        for ia, ib in [(6,7),(8,9),(10,11)]:
            hh = parse_horses(row[ia]); pp = safe_int(row[ib])
            if hh and pp > 0: place_payouts[hh[0]] = pp

        wide_payouts = {}
        for ia, ib in [(12,13),(14,15),(16,17)]:
            pair = parse_horses(row[ia]); pp = safe_int(row[ib])
            if len(pair) == 2 and pp > 0: wide_payouts[frozenset(pair)] = pp

        umaren_pair = parse_horses(row[18]); umaren_p = safe_int(row[19])
        umaren = (frozenset(umaren_pair), umaren_p) if len(umaren_pair) == 2 and umaren_p > 0 else None
        umatan_pair = parse_horses(row[20]); umatan_p = safe_int(row[21])
        umatan = (umatan_pair, umatan_p) if len(umatan_pair) == 2 and umatan_p > 0 else None

        spk_t = parse_horses(row[22]); spk_p = safe_int(row[23])
        sanrenpuku = (frozenset(spk_t), spk_p) if len(spk_t) == 3 and spk_p > 0 else None
        sst_t = parse_horses(row[24]); sst_p = safe_int(row[25])
        sanrentan = (sst_t, sst_p) if len(sst_t) == 3 and sst_p > 0 else None

        date_str = nen + '-' + md[:2] + '-' + md[2:4]
        races[(date_str, venue, rno)] = {
            'winner': winner_h[0],
            'win_payout': winner_p,
            'place_payouts': place_payouts,
            'wide_payouts': wide_payouts,
            'umaren': umaren,
            'umatan': umatan,
            'sanrenpuku': sanrenpuku,
            'sanrentan': sanrentan,
            'race_type': race_type,
            'venue': venue,
            'race_no': rno,
            'date_str': date_str,
            'weekday': ['月','火','水','木','金','土','日'][datetime.strptime(nen+md, '%Y%m%d').weekday()],
            'month': date_str[:7],
        }
    cur.close()

    cur = conn.cursor("se_cur"); cur.itersize = 50000
    cur.execute(f"""
        SELECT kaisai_nen, kaisai_tsukihi, keibajo_code, race_bango,
               umaban, tansho_ninkijun, kakutei_chakujun
        FROM {table_se} WHERE kaisai_nen >= '2025'
    """)
    for row in cur:
        nen, md, code, bango, umaban, ninki, chaku = row
        if race_type == 'jra':
            venue = JRA_VENUES.get(code)
        else:
            venue = NAR_VENUES.get(correct_nar_venue(nen, md, code, schedule))
        if not venue: continue
        try:
            rno = int(bango); h = int(str(umaban).strip()); pop = int(str(ninki).strip())
        except: continue
        date_str = nen + '-' + md[:2] + '-' + md[2:4]
        race = races.get((date_str, venue, rno))
        if race:
            race.setdefault('horses', {})[h] = {'pop': pop, 'finish': safe_int(chaku)}
    cur.close(); conn.close()

    for race in races.values():
        race['field_size'] = len(race.get('horses', {}))

    return races


# --- merge engines + pckeiba ---
def merge(by_race, race_meta, races_pck):
    matched = 0
    for rid, eng_picks in by_race.items():
        date, venue, race_no, race_type = race_meta[rid]
        race = races_pck.get((date, venue, race_no))
        if not race: continue
        votes_top3 = Counter()
        votes_top1 = Counter()
        for engine, (top1, top3) in eng_picks.items():
            for h in (top3 or []):
                if h: votes_top3[h] += 1
            if top1: votes_top1[top1] += 1
        race['votes_top3'] = dict(votes_top3)
        race['votes_top1'] = dict(votes_top1)
        race['matched'] = True
        matched += 1
    return matched


# --- bet construction ---
def construct_bets(race):
    """各戦略についてレース内 bets を生成: list of (strategy, cost_total, payout_total, axis_horse_or_None)"""
    out = []
    win_p = race['win_payout']
    winner = race['winner']
    place_p = race['place_payouts']
    wide_p = race['wide_payouts']
    umaren = race['umaren']
    umatan = race['umatan']
    sanren = race['sanrenpuku']
    sst = race['sanrentan']
    horses = race.get('horses', {})

    votes_top3 = race.get('votes_top3', {})
    votes_top1 = race.get('votes_top1', {})

    cons_t1_4 = [h for h, c in votes_top1.items() if c == 4]
    cons_t1_3plus = [h for h, c in votes_top1.items() if c >= 3]
    cons_t1_2plus = [h for h, c in votes_top1.items() if c >= 2]

    cons_t3_4 = [h for h, c in votes_top3.items() if c == 4]
    cons_t3_3plus = [h for h, c in votes_top3.items() if c >= 3]

    ranked_t3 = sorted(votes_top3.items(), key=lambda x: (-x[1], -votes_top1.get(x[0], 0), x[0]))

    # === 単勝 ===
    # T1: 4-engine top1 一致馬の単勝 (1本)
    for h in cons_t1_4:
        out.append(('T1_4engT1合議の単勝', 100, win_p if h == winner else 0, h))
    # T2: 3-engine top1 一致馬の単勝
    for h in cons_t1_3plus:
        if h in cons_t1_4: continue
        out.append(('T2_3engT1合議の単勝', 100, win_p if h == winner else 0, h))
    # T3: 2-engine top1 一致馬の単勝 (= v5 cons)
    for h in cons_t1_2plus:
        if h in cons_t1_3plus: continue
        out.append(('T3_2engT1合議の単勝', 100, win_p if h == winner else 0, h))
    # T4: 4-engine top3 一致馬の単勝
    for h in cons_t3_4:
        out.append(('T4_4engT3合議の単勝', 100, win_p if h == winner else 0, h))
    # T5: 3-engine top3 一致馬の単勝
    for h in cons_t3_3plus:
        if h in cons_t3_4: continue
        out.append(('T5_3engT3合議の単勝', 100, win_p if h == winner else 0, h))

    # === 複勝 ===
    for h in cons_t1_4:
        out.append(('F1_4engT1合議の複勝', 100, place_p.get(h, 0), h))
    for h in cons_t1_3plus:
        if h in cons_t1_4: continue
        out.append(('F2_3engT1合議の複勝', 100, place_p.get(h, 0), h))
    for h in cons_t1_2plus:
        if h in cons_t1_3plus: continue
        out.append(('F3_2engT1合議の複勝', 100, place_p.get(h, 0), h))
    for h in cons_t3_4:
        out.append(('F4_4engT3合議の複勝', 100, place_p.get(h, 0), h))
    for h in cons_t3_3plus:
        if h in cons_t3_4: continue
        out.append(('F5_3engT3合議の複勝', 100, place_p.get(h, 0), h))

    # === ワイド ===
    if len(ranked_t3) >= 2:
        h1, h2 = ranked_t3[0][0], ranked_t3[1][0]
        out.append(('W1_TOP2投票の_W1点', 100, wide_p.get(frozenset({h1,h2}), 0), None))
    if len(ranked_t3) >= 3:
        t3 = [r[0] for r in ranked_t3[:3]]
        for c1, c2 in combinations(t3, 2):
            out.append(('W2_TOP3投票の_W_BOX3', 100, wide_p.get(frozenset({c1,c2}), 0), None))
    # 4-eng top1合議 軸 + ranked_t3 流し
    for axis in cons_t1_4:
        others = [r[0] for r in ranked_t3 if r[0] != axis][:3]
        for h2 in others:
            out.append(('W3_4engT1軸_W流し', 100, wide_p.get(frozenset({axis,h2}), 0), axis))

    # === 馬連 ===
    if umaren:
        umaren_pair, umaren_pay = umaren
        if len(ranked_t3) >= 2:
            h1, h2 = ranked_t3[0][0], ranked_t3[1][0]
            out.append(('U1_TOP2投票の馬連1点', 100,
                       umaren_pay if frozenset({h1,h2}) == umaren_pair else 0, None))
        if len(ranked_t3) >= 3:
            t3 = [r[0] for r in ranked_t3[:3]]
            for c1, c2 in combinations(t3, 2):
                out.append(('U2_TOP3投票の馬連BOX3', 100,
                           umaren_pay if frozenset({c1,c2}) == umaren_pair else 0, None))

    # === 馬単 ===
    if umatan:
        umatan_pair, umatan_pay = umatan
        # X1: TOP2投票 BOX 2点 (順序2通り)
        if len(ranked_t3) >= 2:
            h1, h2 = ranked_t3[0][0], ranked_t3[1][0]
            for ord_pair in [(h1,h2),(h2,h1)]:
                out.append(('X1_TOP2投票の馬単BOX2', 100,
                           umatan_pay if ord_pair == umatan_pair else 0, None))
        # X2: 4-eng top1合議 軸 1着固定 + 流し
        for axis in cons_t1_4:
            others = [r[0] for r in ranked_t3 if r[0] != axis][:3]
            for h2 in others:
                out.append(('X2_4engT1軸_馬単1着固定流し', 100,
                           umatan_pay if (axis, h2) == umatan_pair else 0, axis))

    # === 三連複 ===
    if sanren:
        sp_set, sp_pay = sanren
        if len(ranked_t3) >= 3:
            top3_set = frozenset({ranked_t3[i][0] for i in range(3)})
            out.append(('S1_TOP3投票の三連複1点', 100,
                       sp_pay if top3_set == sp_set else 0, None))
        if len(ranked_t3) >= 4:
            top4 = [ranked_t3[i][0] for i in range(4)]
            for combo in combinations(top4, 3):
                out.append(('S2_TOP4投票の三連複BOX4', 100,
                           sp_pay if frozenset(combo) == sp_set else 0, None))
        if len(ranked_t3) >= 5:
            top5 = [ranked_t3[i][0] for i in range(5)]
            for combo in combinations(top5, 3):
                out.append(('S3_TOP5投票の三連複BOX10', 100,
                           sp_pay if frozenset(combo) == sp_set else 0, None))
        for axis in cons_t1_4:
            others = [r[0] for r in ranked_t3 if r[0] != axis][:4]
            for combo in combinations(others, 2):
                out.append(('S4_4engT1軸_三連複流し', 100,
                           sp_pay if frozenset({axis, *combo}) == sp_set else 0, axis))

    # === 三連単 ===
    if sst:
        sst_t, sst_pay = sst
        # Y1: 4-eng top1合議 軸 1着固定 + TOP4から2-3着流し (順序6通り = 6点)
        for axis in cons_t1_4:
            others = [r[0] for r in ranked_t3 if r[0] != axis][:3]
            for combo in permutations(others, 2):
                out.append(('Y1_4engT1軸_三連単1着固定流し', 100,
                           sst_pay if (axis, combo[0], combo[1]) == sst_t else 0, axis))

    return out


# --- aggregate ---
def aggregate(races, segment_func):
    """segment_func: race -> list of segment keys
    Returns: {strategy: {seg_key: {n, hits, payout, invest, raw_payouts list}}}
    """
    results = defaultdict(lambda: defaultdict(lambda: {
        'n': 0, 'invest': 0, 'payout': 0, 'hits': 0, 'samples': []
    }))
    for race in races:
        if not race.get('matched'): continue
        bets = construct_bets(race)
        if not bets: continue
        segs = segment_func(race)
        for strat, cost, payout, axis in bets:
            for seg_key in segs:
                s = results[strat][seg_key]
                s['n'] += 1
                s['invest'] += cost
                s['payout'] += payout
                if payout > 0: s['hits'] += 1
                # Sample for bootstrap (only for top-level filters)
                if seg_key.startswith('ALL') or seg_key.startswith('RT='):
                    s['samples'].append(payout - cost)
    return results


def bootstrap_ci(profits, n_resamples=1000, ci=0.95):
    """Bootstrap CI for mean profit per ¥100 bet (recovery rate - 100)."""
    if not profits or len(profits) < 30:
        return None, None
    means = []
    n = len(profits)
    for _ in range(n_resamples):
        sample = [profits[random.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(n_resamples * (1 - ci) / 2)]
    hi = means[int(n_resamples * (1 + ci) / 2)]
    # recovery = 1 + mean / 100 (since each invest is 100yen)
    return (1 + lo / 100) * 100, (1 + hi / 100) * 100


def render_report(results_all, results_month, output_path):
    lines = [
        '# フル検証 (clean データ) — leakage除去後の本当の数字\n',
        f'**生成**: {datetime.now().strftime("%Y-%m-%d %H:%M")}\n',
        '**手法**: created_at < race_date (または同日09:00 JST前) のみ採用 (強化leakage除去)\n',
        '**期間**: 2026-03 ~ 2026-04 (2ヶ月)\n',
        '**統計**: Bootstrap 1,000回 95%信頼区間, Mar/Apr stability check\n',
        '\n## 注意\n',
        '- clean データは2ヶ月のみ → 季節バイアス・偶然のブレ排除困難\n',
        '- production判断は CI下限>110% AND Mar/Apr両方>100% AND n>=100 が最低基準\n',
        '- **多重比較**: 本レポートは複数セグメント(戦略×会場×曜日)を同一データで同時検定。\n',
        '  Bonferroni補正目安: 100セグメント検定なら有効α=0.05/100=0.0005相当。\n',
        '  S/A級採択はあくまで"発見フェーズ"の候補リストであり、独立OOSデータでの再検証を要する。\n',
        '\n---\n\n',
    ]

    # === Top patterns by recovery (with confidence) ===
    candidates = []
    for strat, segs in results_all.items():
        for seg, d in segs.items():
            if d['n'] < 50: continue
            if d['invest'] == 0: continue
            recov = d['payout'] / d['invest'] * 100
            ci_lo, ci_hi = bootstrap_ci(d['samples']) if d['samples'] else (None, None)

            # Mar/Apr split
            mar_d = results_month.get(strat, {}).get(seg + '|2026-03', {'n':0,'invest':0,'payout':0})
            apr_d = results_month.get(strat, {}).get(seg + '|2026-04', {'n':0,'invest':0,'payout':0})
            mar_recov = mar_d['payout'] / mar_d['invest'] * 100 if mar_d['invest'] else 0
            apr_recov = apr_d['payout'] / apr_d['invest'] * 100 if apr_d['invest'] else 0

            # Production-ready criteria
            ready = '❌'
            if d['n'] >= 100 and ci_lo is not None and ci_lo >= 110 and mar_recov >= 100 and apr_recov >= 100 and mar_d['n'] >= 30 and apr_d['n'] >= 30:
                ready = '🌟 S'
            elif d['n'] >= 80 and recov >= 130 and mar_recov >= 90 and apr_recov >= 90:
                ready = '✅ A'
            elif d['n'] >= 50 and recov >= 110:
                ready = '🟡 B'

            candidates.append({
                'strat': strat, 'seg': seg, 'n': d['n'], 'hits': d['hits'],
                'invest': d['invest'], 'payout': d['payout'],
                'recov': recov, 'ci_lo': ci_lo, 'ci_hi': ci_hi,
                'mar_n': mar_d['n'], 'mar_recov': mar_recov,
                'apr_n': apr_d['n'], 'apr_recov': apr_recov,
                'ready': ready,
            })

    candidates.sort(key=lambda x: (-(1 if x['ready'].startswith('🌟') else 0),
                                    -(1 if x['ready'].startswith('✅') else 0),
                                    -x['recov']))

    # === Production-ready patterns ===
    s_tier = [c for c in candidates if c['ready'].startswith('🌟')]
    a_tier = [c for c in candidates if c['ready'].startswith('✅')]
    b_tier = [c for c in candidates if c['ready'].startswith('🟡')]

    lines.append('# 🌟 S級 — Production Ready Pattern (production即組込み候補)\n\n')
    lines.append('条件: n>=100 AND Bootstrap CI下限>=110% AND Mar>=100% AND Apr>=100%\n\n')
    if s_tier:
        lines.append('| 戦略 | セグメント | n | 回収率 | CI下限 | CI上限 | Mar(n) | Mar回収 | Apr(n) | Apr回収 |\n')
        lines.append('|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n')
        for c in s_tier:
            lines.append(f'| {c["strat"]} | {c["seg"]} | {c["n"]:,} | **{c["recov"]:.1f}%** | '
                         f'{c["ci_lo"]:.1f}% | {c["ci_hi"]:.1f}% | {c["mar_n"]} | {c["mar_recov"]:.1f}% | '
                         f'{c["apr_n"]} | {c["apr_recov"]:.1f}% |\n')
    else:
        lines.append('**S級該当なし** — 現在の clean データだけでは、production-ready と断言できる pattern は無い。\n\n')

    lines.append('\n# ✅ A級 — 有望候補 (要追加検証)\n\n')
    lines.append('条件: n>=80 AND 回収率>=130% AND Mar>=90% AND Apr>=90%\n\n')
    if a_tier:
        lines.append('| 戦略 | セグメント | n | 回収率 | CI下限 | Mar回収 | Apr回収 |\n')
        lines.append('|---|---|---:|---:|---:|---:|---:|\n')
        for c in a_tier[:30]:
            ci_lo_str = f'{c["ci_lo"]:.1f}%' if c['ci_lo'] is not None else 'N/A'
            lines.append(f'| {c["strat"]} | {c["seg"]} | {c["n"]:,} | **{c["recov"]:.1f}%** | '
                         f'{ci_lo_str} | {c["mar_recov"]:.1f}% | {c["apr_recov"]:.1f}% |\n')
    else:
        lines.append('A級該当なし\n\n')

    lines.append('\n# 🟡 B級 — 観察対象 (n>=50 & 回収率>=110%)\n\n')
    if b_tier:
        lines.append('| 戦略 | セグメント | n | 回収率 | Mar回収 | Apr回収 |\n')
        lines.append('|---|---|---:|---:|---:|---:|\n')
        for c in b_tier[:50]:
            lines.append(f'| {c["strat"]} | {c["seg"]} | {c["n"]:,} | {c["recov"]:.1f}% | '
                         f'{c["mar_recov"]:.1f}% | {c["apr_recov"]:.1f}% |\n')

    # === 全戦略の race_type ベース全体集計 ===
    lines.append('\n\n# 📊 全戦略 × race_type 全体集計\n\n')
    strats = sorted(results_all.keys())
    lines.append('| 戦略 | NAR(n) | NAR回収 | JRA(n) | JRA回収 |\n')
    lines.append('|---|---:|---:|---:|---:|\n')
    for s in strats:
        nar = results_all[s].get('RT=nar', {'n':0,'invest':0,'payout':0})
        jra = results_all[s].get('RT=jra', {'n':0,'invest':0,'payout':0})
        nar_r = nar['payout']/nar['invest']*100 if nar['invest'] else 0
        jra_r = jra['payout']/jra['invest']*100 if jra['invest'] else 0
        lines.append(f'| {s} | {nar["n"]:,} | {nar_r:.1f}% | {jra["n"]:,} | {jra_r:.1f}% |\n')

    # === 全候補ランキング ===
    lines.append('\n\n# 全候補ランキング (回収率順, n>=50)\n\n')
    cands_sorted = sorted(candidates, key=lambda x: -x['recov'])
    lines.append('| Rank | 戦略 | セグメント | n | 回収率 | Mar | Apr | rating |\n')
    lines.append('|---|---|---|---:|---:|---:|---:|---|\n')
    for i, c in enumerate(cands_sorted[:80], 1):
        lines.append(f'| {i} | {c["strat"]} | {c["seg"]} | {c["n"]:,} | **{c["recov"]:.1f}%** | '
                     f'{c["mar_recov"]:.1f}% | {c["apr_recov"]:.1f}% | {c["ready"]} |\n')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f'report → {output_path}')


def main():
    print('loading clean engine_hit_rates...')
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    by_race, race_meta = load_clean_engine(sb)
    print(f'  unique clean races (>=3 engines): {len(by_race)}')

    schedule = load_schedule()
    print('loading PCKEIBA payouts...')
    nar = load_pckeiba('nvd_se', 'nvd_hr', 'nar', schedule)
    jra = load_pckeiba('jvd_se', 'jvd_hr', 'jra', schedule)
    races_pck = {**nar, **jra}
    print(f'  total: {len(races_pck)} (NAR {len(nar)} / JRA {len(jra)})')

    matched = merge(by_race, race_meta, races_pck)
    print(f'  matched: {matched}')

    races_list = [r for r in races_pck.values() if r.get('matched')]

    def seg_all(race):
        rt = race['race_type']
        v = race['venue']
        wd = race['weekday']
        return [
            'ALL=all',
            f'RT={rt}',
            f'VENUE={rt}/{v}',
            f'WD={rt}/{wd}',
        ]

    def seg_month(race):
        m = race['month']
        rt = race['race_type']
        v = race['venue']
        wd = race['weekday']
        return [
            f'ALL=all|{m}',
            f'RT={rt}|{m}',
            f'VENUE={rt}/{v}|{m}',
            f'WD={rt}/{wd}|{m}',
        ]

    print('aggregating overall...')
    results_all = aggregate(races_list, seg_all)
    print('aggregating by month...')
    results_month = aggregate(races_list, seg_month)

    out_path = os.path.join(DOCS_DIR, f'full_validation_clean_{datetime.now().strftime("%Y%m%d")}.md')
    render_report(results_all, results_month, out_path)
    print('done.')


if __name__ == '__main__':
    main()
