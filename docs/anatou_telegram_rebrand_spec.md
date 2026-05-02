# 穴党参謀AI Telegram 配信リブランド仕様書

最終更新: 2026-05-01
ステータス: ✅ jin さん確認済み、実装着手

---

## 1. 目的

Telegram チャンネル（Bot `@anatoukeibabot` / chat_id `-1003987167999`）の配信を
**「競馬GANTZ」キャラ → 「穴党参謀AI」キャラ**にリブランド。
note 記事と文体・ブランドを統一し、Dlogic 完全非露出の運用に揃える。

## 2. 経緯

- 4/26 から「競馬GANTZ」として GANTZ 漫画モチーフの口調で配信開始
- 5/1 note 投稿を「穴党参謀AI」として復活、淡々とした予想家トーンに統一
- 同日、Telegram 側も note と同じブランド・口調へ移行を決定

## 3. ブランドルール（最重要）

### 3.1 名称
- 公開名称: **穴党参謀AI**
- bot: `@anatoukeibabot`（既存、変更なし）
- チャンネル表示名: jin さん側で手動変更予定

### 3.2 禁止表現（GANTZ 漫画ネタ — 完全削除）

| カテゴリ | NG ワード |
|---|---|
| 語尾 | 「で だす」「し まち」「し まちた」「し まち ょう」「くだちい」「で だす ね」 |
| GANTZ 世界観名詞 | 「玉」「任務」「撃破」 |
| GANTZ セリフ流用 | 「あなた 達 の 馬券 は もう ない」「新しい 馬券 を あげまし ょう」 |
| スペース区切り | 文章中の不自然なスペース挿入（例: 「玉 は 静か で だす」） |
| 哲学フレーズ | 「ほとんど 失敗 し まち」「1点で 全額 回収 が 仕様 で だす」 |

### 3.3 残す表現（普通の予想用語）

「ターゲット」「本命」「狙い目」「妙味」「穴」「軸」「相手」「人気薄」「単勝」など、
予想家として通常使う言葉は残す。

### 3.4 統一表現（note と共通）
- ❌ Dlogic / Ilogic / ViewLogic / MLlogic / D-Logic / dlogic.ai / dlogicai
- ✅ 「独自AI分析」「独自指数」「独自ロジック」「独自AI 4基」「合議AI」「穴党参謀AI」

### 3.5 トーン
- **淡々とした予想家トーン**
- 「〜と分析しています」「〜が妙味です」「狙い目です」「外しても続けたい」
- 漫画キャラ感を排除、信頼性重視

## 4. 対象スクリプトと変更内容

| # | ファイル | 配信時刻 | 変更内容 |
|---|---|---|---|
| 1 | `anatou_greet.py` | 08:00 | GANTZ口調全削除、朝の挨拶 + 昨日の戦果を淡々 |
| 2 | `anatou_post_strict.py` | 09:00 | Layer 1-3 任務指令、各ターゲットに「なぜ妙味か」短文（既存より控えめ）、note と差別化のため Telegram 用は要点のみ |
| 3 | `anatou_post_loose.py` | 09:30 | 既に普通だが「穴党参謀AI」ブランド名を入れて統一 |
| 4 | `anatou_post_results.py` | 23:00 | 「撃破」→「的中」、戦果報告を淡々表記 |
| 5 | `anatou_correction_notice.py` | 随時 | 訂正通知の文言を穴党参謀AI スタイルに |
| 6 | `anatou_backfill_intro.py` | 1回限り | 過去実績紹介の文言を穴党参謀AI スタイルに |

## 5. 配信タイミング・頻度

**変更なし**。既存の systemd timer をそのまま流用。

```
08:00 JST  anatou-greet.timer
09:00 JST  anatou-strict.timer
09:30 JST  anatou-loose.timer
23:00 JST  anatou-results.timer
```

## 6. note リンク

**貼らない**（jin さん指示）。Telegram は Telegram 内で完結、note への誘導は行わない。

## 7. 文体ガイドライン（具体例）

### Before（GANTZ）
```
☀️ <b>5/1(金) 任務開始</b>

🔥🔥🔥 <b>Layer 1 — 本命厳格 (旧強5会場)</b> 🔥🔥🔥
🚨 全ターゲット <b>単勝100円</b>

━ <b>ターゲット1</b> ━
📍 <b>船橋 7R</b>  ⏰ <b>15:25</b>
🐎 <b>5番 ヒロイン</b> (6人気)
🎯 単勝 <b>5</b>
🤝 一致 <b>3/4</b> エンジン

💎 <b>運用ルール</b>
・ほとんど 失敗 し まち
・"1点で 全額 回収" が 仕様 で だす
```

### After（穴党参謀AI）
```
☀️ <b>5/1(金) 穴党参謀AI 本日の本命</b>

🔥 <b>Layer 1 — 本命厳格（旧強5会場）</b>
全ターゲット <b>単勝100円</b>

━ <b>本命1</b> ━
📍 <b>船橋 7R</b>  ⏰ 15:25
◎ <b>5番 ヒロイン</b>（6番人気）
🎯 単勝 100円
🤝 独自AI 4基中3基が一致

📊 <b>運用ルール</b>
・各ターゲット 100円 固定
・人気薄狙いのため的中率は低め
・1点的中で投資額をカバーする運用
```

### 締めの違い
- Before: 「毎日 結果 を 正直 に 公開 し まち」
- After:  「毎日の結果は正直に公開しています。」

## 8. 危険人気馬は配信しない

note では「危険人気馬」+「人気薄推奨」の統合だが、
**Telegram は人気薄推奨のみ**（既存通り、変更なし）。

理由：
- Telegram は速報・短尺の媒体特性
- 危険人気馬は文字数増大、note でのマネタイズ要素
- 役割分担: Telegram = 推奨速報 / note = 詳細解説 + 危険馬警告

## 9. ブランド隠蔽の二重チェック

`anatou_telegram_lib.py` の `send_telegram()` 直前に、
note と同じ禁止ワード grep を入れる（`unified.brand_guard.assert_clean` 相当を Python 内蔵で簡易実装）。
混入したらログのみ出して送信中止。

実装：`anatou_telegram_lib.py` に `assert_clean(text)` を追加。

## 10. デプロイ

VPS `/opt/dlogic/linebot/scripts/` に SCP。
systemd timer 再起動不要（スクリプト本体だけ差し替え）。

```bash
scp anatou_greet.py anatou_post_strict.py anatou_post_results.py \
    anatou_correction_notice.py anatou_backfill_intro.py anatou_post_loose.py \
    anatou_telegram_lib.py \
    root@220.158.24.157:/opt/dlogic/linebot/scripts/
```

## 11. 動作確認

### ローカル dry-run
- 各スクリプトの `format_*()` 関数を直接呼んで stdout に出力
- 過去日付（5/1, 4/29 等）でテスト
- 禁止ワード grep で Dlogic 系混入なし確認

### VPS 即時配信テスト
- 23:00 戦果報告を本日中に手動キック → 新口調で 1 通配信
- jin さんに視認確認いただく
- 問題なければ翌日 08:00 から自動で新口調運用

## 12. 実装フェーズ

| Phase | 作業 | 完了条件 |
|---|---|---|
| A | 仕様書（この文書） | jin さん OK |
| B1 | anatou_greet.py 書き換え | 単体実行で新口調出力 |
| B2 | anatou_post_strict.py 書き換え | 単体実行で新口調出力 |
| B3 | anatou_post_results.py 書き換え | 単体実行で新口調出力 |
| B4 | anatou_correction_notice.py + backfill_intro.py 書き換え | 単体実行で新口調出力 |
| B5 | anatou_post_loose.py + lib にブランド統一 | 単体実行で新口調出力 |
| C | VPS デプロイ + 即時テスト配信 | jin さん視認 OK |

---

## 13. 確認事項（jin さん回答 2026-05-01）

| # | 質問 | 回答 |
|---|---|---|
| 1 | note リンクの貼り方 | **貼らない**（c） |
| 2 | 「ターゲット」など予想用語 | **残す**、GANTZ風のみ削除 |
| 3 | 締めの哲学フレーズ | **note と同じ淡々口調** |
| 4 | Bot 名・チャンネル表示名変更 | jin さん側で対応 |
| 5 | 既存 GANTZ ファン対応 | 即座切り替え（読者ゼロ） |

→ Phase B 着手。
