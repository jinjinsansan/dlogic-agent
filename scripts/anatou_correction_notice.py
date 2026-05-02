#!/usr/bin/env python3
"""訂正告知 - 必要時に手動実行する一回限りの配信スクリプト.

過去のテンプレ（v5 → v6 切替告知）を雛形として残す。
内容は実行前に編集して使う想定。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anatou_telegram_lib import send_telegram_long, setup_logging

logger = setup_logging()

MSG = """⚠️ <b>訂正のお知らせ</b>

本日朝の配信に誤りがあったため、訂正します。

<b>調査結果</b>:
・配信の根拠となったバックテストデータに leakage（情報汚染）が含まれていました
・1年データの 76% が後付け再評価で、未来情報を含んでいました
・clean（汚染除去）データで同ルールを検証した結果、回収率 0% でした

<b>訂正後の運用方針</b>:
・clean データで唯一統計的に強い戦略を再発見しました
・条件: <b>NAR + 火水木 + 旧強5会場 + 6-12頭 + 5-8人気 + 2-3エンジン一致</b> → 単勝
・clean 2ヶ月実績（n=145）: 回収率 <b>396.9%</b> / Bootstrap 95%信頼下限 <b>225%</b>

<b>本日の自動投票は全停止しました</b>。

<b>明日からの運用</b>:
・新ルール（v6）で自動配信 + 自動投票再開
・100円単位で当たり外れを全公開
・誇大表記を廃止、CI下限ベースで数字を出します

ご迷惑をおかけしました。
正確な情報をお届けするため、誤ったデータは即時撤回しています。"""


def main():
    ok = send_telegram_long(MSG)
    logger.info(f"correction sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
