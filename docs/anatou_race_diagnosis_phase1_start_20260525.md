# 穴党参謀AI レース診断AI Phase 1 開始レポート 2026-05-25

## 実施内容

計画書を「ワイド期待値レイヤー主軸」から「レース診断AI主軸」へ書き換えた。

更新した計画書:

- `docs/anatou_pair_value_ai_development_plan_20260525.md`

追加したスクリプト:

- `scripts/anatou_race_diagnosis.py`

生成したデータ:

- `data/anatou_race_diagnosis_jra_20260301_20260430.jsonl`
- `data/anatou_race_diagnosis_nar_20260301_20260430.jsonl`

生成したレポート:

- `docs/anatou_race_diagnosis_build_jra_20260301_20260430.md`
- `docs/anatou_race_diagnosis_build_nar_20260301_20260430.md`

## 診断項目

各レースに以下を付与する。

- AI一致度
- AI意見割れ
- 市場ギャップ
- 荒れ度
- watch score
- AI穴馬
- 危険人気馬
- AI中心馬
- primary label
- suggested use
- summary text

## JRA 診断結果

- records: 395
- watch labels: 298
- with AI holes: 394
- with danger popular: 159

primary label:

- `market_gap`: 159
- `ai_consensus`: 139
- `hole_candidate`: 97

suggested use:

- `hole_check`: 235
- `danger_popular_check`: 159
- `skip`: 1

サンプル:

```text
2026-04-12 阪神8R
診断=market_gap
用途=danger_popular_check
AI穴馬 2番(5人気, 3基支持)
危険人気 10番(2人気, AI支持1基)
AI中心 8番(4基支持)
```

## NAR 診断結果

- records: 1,343
- watch labels: 1,203
- with AI holes: 1,342
- with danger popular: 759

primary label:

- `market_gap`: 759
- `hole_candidate`: 327
- `ai_consensus`: 257

suggested use:

- `danger_popular_check`: 759
- `hole_check`: 583
- `skip`: 1

サンプル:

```text
2026-04-01 船橋12R
診断=hole_candidate
用途=hole_check
AI穴馬 3番(7人気, 4基支持)
AI中心 3番(4基支持)
```

## 初期所感

レース診断として読む形は作れた。

ただし、現状ではAI穴馬がほぼ全レースに出ており、診断が多すぎる可能性がある。サービスとしては、もっと絞り込みが必要。

次に検証すること:

- AI穴馬が実際に馬券内へ来ているか
- 危険人気馬が実際に凡走しているか
- `market_gap` ラベルが高配当レースを拾えているか
- `skip` が少なすぎるため、見送り条件を強化する必要があるか

## 次の実装

次は以下を作る。

- `scripts/anatou_race_diagnosis_backtest.py`

評価内容:

- ラベル別のレース傾向
- AI穴馬の複勝圏率
- 危険人気馬の凡走率
- watch score別の高配当発生率
- suggested use別の特徴

ここで「診断として価値があるか」を見る。

