#!/usr/bin/env python3
"""一回限り: 朝の v5 投稿を訂正し、v6 (Layer 1) ルールに切替を告知."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anatou_telegram_lib import send_telegram, setup_logging

logger = setup_logging()

MSG = """⚠️ <b>重要 訂正 告知</b>

本日 朝 09:00 の 配信 (信頼度・高 9件 大井) は <b>誤り</b> で した。

調査 の 結果、配信 の 根拠 と なった バックテスト データ に <b>leakage (情報汚染)</b> が 含まれて いた こと が 判明 し まちた。

<b>具体的に</b>:
・1年データ の 76% が 後付け 再評価 で、未来 の 情報 を 含んで いた
・320% / 141% など の 数字 は 過大評価 で だす
・clean (汚染除去) データ で 同 ルール を 検証 し た 結果、回収率 0% で した

<b>訂正後 の 真実</b>:
・clean データ で 唯一 統計的 に 強い 戦略 を 再発見 し まちた
・条件: <b>NAR + 火水木 + 旧強5会場 + 6-12頭 + 5-8人気 + 2-3 エンジン一致</b> → 単勝
・clean 2ヶ月実績 (n=145): 回収率 <b>396.9%</b> / Bootstrap 95%信頼下限 <b>225%</b>

<b>今日 の 自動投票 は 全 停止 し まちた</b>。GUI から bet_signals 9件 削除済み。

<b>明日 から の 運用</b>:
・新ルール (v6) で 自動配信 + 自動投票 再開
・100円単位 で 当たり 外れ 全部 公開
・誇大表記 廃止、honest CI下限 ベース で 数字 を 出し まち

御免 で だす。
規律 を 守る ため に、<b>嘘 の データ は 即刻 撤回 し まちた</b>。

このまま 残す と クリスト も ガンツ も 怒る で だす。"""


def main():
    ok = send_telegram(MSG)
    logger.info(f"correction sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
