"""Scrape race results (着順 + 払戻) from netkeiba."""

import logging
import re

from config import NETKEIBA_JRA_BASE, NETKEIBA_NAR_BASE
from scrapers.base import fetch_with_retry

logger = logging.getLogger(__name__)


def fetch_race_result(race_id: str, race_type: str = "jra") -> dict | None:
    """Fetch race result for a given race_id.

    Returns dict with:
        race_id: str
        finishing_order: list[dict]  — [{position, horse_number, horse_name}, ...]
        winner_number: int
        winner_name: str
        win_payout: int  — 単勝払戻金額 (円)
        status: "finished" | "cancelled"
    Or None if page not found / race not yet finished.
    """
    if race_type == "nar":
        url = f"{NETKEIBA_NAR_BASE}/race/result.html?race_id={race_id}"
    else:
        url = f"{NETKEIBA_JRA_BASE}/race/result.html?race_id={race_id}"

    soup = fetch_with_retry(url, encoding="euc-jp", timeout=15)
    if not soup:
        return None

    # --- Parse result table ---
    table = soup.select_one("table.RaceTable01")
    if not table:
        logger.warning(f"No RaceTable01 found for {race_id}")
        return None

    # Select data rows: skip header row (class="Header"), take rows with td.Result_Num
    rows = [tr for tr in table.select("tr") if tr.select("td.Result_Num")]
    if not rows:
        # Fallback: try legacy selector
        rows = table.select("tr.HorseList")
    if not rows:
        logger.info(f"No result rows for {race_id} — race may not be finished")
        return None

    finishing_order = []
    for tr in rows:
        tds = tr.select("td")
        if len(tds) < 4:
            continue

        pos_text = tds[0].get_text(strip=True)
        # Handle non-numeric positions: 中止, 除外, 取消 etc.
        try:
            position = int(pos_text)
        except ValueError:
            position = 0  # DNF / scratched

        try:
            horse_number = int(tds[2].get_text(strip=True))
        except ValueError:
            continue

        horse_name = tds[3].get_text(strip=True)

        finishing_order.append({
            "position": position,
            "horse_number": horse_number,
            "horse_name": horse_name,
        })

    if not finishing_order:
        return None

    # Sort by position (0 = DNF goes to end)
    finishing_order.sort(key=lambda x: (x["position"] == 0, x["position"]))

    # Winner
    winner = finishing_order[0]
    winner_number = winner["horse_number"]
    winner_name = winner["horse_name"]

    # --- Parse payout table (全馬券種) ---
    pay_back = soup.select_one(".Result_Pay_Back")
    payouts = _parse_payouts(pay_back) if pay_back else {}
    win_entry = payouts.get("win") or {}
    win_payout = win_entry.get("payout") or 0

    # Build result_json with top 3 + 全馬券種 payouts
    result_json = {
        "top3": finishing_order[:3],
        "total_horses": len(finishing_order),
        "payouts": payouts,
    }

    return {
        "race_id": race_id,
        "finishing_order": finishing_order,
        "winner_number": winner_number,
        "winner_name": winner_name,
        "win_payout": win_payout,
        "result_json": result_json,
        "status": "finished",
    }


# ============================================================================
# Payout parsing helpers (Netkeiba .Result_Pay_Back table)
# ============================================================================

def _try_int(s: str) -> "int | None":
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _parse_yen(s: str) -> "int | None":
    """'250円' / '1,250円' / '8,900' → 整数。失敗時 None."""
    m = re.search(r"([\d,]+)", s)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _split_lines(td) -> list:
    """Netkeiba の <td> 内 <br> 区切りを行リストに。"""
    return [s.strip() for s in td.get_text(separator="\n").split("\n") if s.strip()]


def _combo_single(result_td) -> "list[int] | None":
    """馬連・馬単・3連複・3連単: 単一 <ul> の <li><span> 全部を1組として返す."""
    if not result_td:
        return None
    spans = result_td.select("ul li span")
    nums = [_try_int(s.get_text(strip=True)) for s in spans]
    nums = [n for n in nums if n is not None]
    return nums if len(nums) >= 2 else None


def _combo_multi(result_td) -> list:
    """ワイド: 複数 <ul> があり各 ul が1組."""
    if not result_td:
        return []
    out = []
    for ul in result_td.select("ul"):
        spans = ul.select("li span")
        nums = [_try_int(s.get_text(strip=True)) for s in spans]
        nums = [n for n in nums if n is not None]
        if len(nums) >= 2:
            out.append(nums)
    return out


def _parse_payouts(pay_back) -> dict:
    """Netkeiba .Result_Pay_Back から全馬券種払戻を抽出.

    Returns dict (空なら {}):
      win: {"combo": [n], "payout": int}
      fukusho: [{"horse_number": int, "payout": int}, ...]
      umaren / wide / umatan: [{"combo": [n,m], "payout": int}, ...]
      sanrenpuku / sanrentan: [{"combo": [a,b,c], "payout": int}, ...]
    """
    out: dict = {}
    if not pay_back:
        return out

    for pt in pay_back.select("table.Payout_Detail_Table"):
        for tr in pt.select("tr"):
            th = tr.select_one("th")
            result_td = tr.select_one("td.Result")
            payout_td = tr.select_one("td.Payout")
            if not (th and result_td and payout_td):
                continue
            kind = th.get_text(strip=True)
            res_lines = _split_lines(result_td)
            pay_lines = _split_lines(payout_td)
            if not res_lines or not pay_lines:
                continue

            try:
                if "単勝" in kind:
                    hn = _try_int(res_lines[0])
                    pay = _parse_yen(pay_lines[0])
                    if hn and pay:
                        out["win"] = {"combo": [hn], "payout": pay}
                elif "複勝" in kind:
                    items = []
                    for hn_str, pay_str in zip(res_lines, pay_lines):
                        hn = _try_int(hn_str)
                        pay = _parse_yen(pay_str)
                        if hn and pay:
                            items.append({"horse_number": hn, "payout": pay})
                    if items:
                        out["fukusho"] = items
                elif "枠連" in kind:
                    pass  # 不要
                elif "馬連" in kind:
                    c = _combo_single(result_td)
                    p = _parse_yen(pay_lines[0])
                    if c and p:
                        out["umaren"] = [{"combo": c, "payout": p}]
                elif "ワイド" in kind:
                    items = []
                    for combo, ps in zip(_combo_multi(result_td), pay_lines):
                        p = _parse_yen(ps)
                        if combo and p:
                            items.append({"combo": combo, "payout": p})
                    if items:
                        out["wide"] = items
                elif "馬単" in kind:
                    c = _combo_single(result_td)
                    p = _parse_yen(pay_lines[0])
                    if c and p:
                        out["umatan"] = [{"combo": c, "payout": p}]
                elif "三連複" in kind or "3連複" in kind:
                    c = _combo_single(result_td)
                    p = _parse_yen(pay_lines[0])
                    if c and p:
                        out["sanrenpuku"] = [{"combo": c, "payout": p}]
                elif "三連単" in kind or "3連単" in kind:
                    c = _combo_single(result_td)
                    p = _parse_yen(pay_lines[0])
                    if c and p:
                        out["sanrentan"] = [{"combo": c, "payout": p}]
            except Exception as e:
                logger.warning(f"_parse_payouts row failed kind={kind}: {e}")
                continue
    return out
