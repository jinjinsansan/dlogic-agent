"""Tone-aware system message templates for MYBOT.

Each tone key maps to a dict of message templates.
Templates may contain {placeholders} for format().
Fallback: casual → if a tone is missing or custom text, use casual.
"""

TONE_MESSAGES: dict[str, dict[str, str]] = {
    # ── casual (タメ口) ── default ──
    "casual": {
        "thinking":          "考え中...",
        "error":             "ごめん、ちょっとエラーが出ちゃった。もう一回言ってもらえる？",
        "honmei_prompt":     "お前の本命を教えてくれ！👇",
        "honmei_registered": "👊 {num}番 {name} を本命で登録したぜ！\n\nみんなの予想に追加したからな。結果出たら回収率も計算してやるよ。",
        "honmei_no_race":    "どのレースの本命か分からなかった。先にレースを見てから選んでくれ！",
        "honmei_blocking":   "おっと、ちょっと待ってくれ！\n\n「みんなの予想」を集めてるんだ。\nみんなの本命を集計して、回収率ランキングを出していく予定なんだよ。\n\nどうか協力してやってくれ🙏\n\n👇 下のボタンから本命をタップ！",
        "honmei_unstable":   "今ちょっと登録が不安定みたいだ。少し時間おいてもう一回お願い！",
        "tool_heavy_prefix":  "⚡ エンジン起動中...",
        "tool_light_prefix":  "🔍 データ取得中...",
        "tool_heavy_suffix":  "少し待ってな（10〜30秒くらい）",
    },

    # ── keigo (敬語) ──
    "keigo": {
        "thinking":          "少々お待ちください...",
        "error":             "申し訳ございません、エラーが発生しました。もう一度お試しいただけますか？",
        "honmei_prompt":     "本命馬をお選びください👇",
        "honmei_registered": "✨ {num}番 {name} を本命として登録いたしました！\n\nみんなの予想に追加しました。結果が出ましたら回収率も計算いたします。",
        "honmei_no_race":    "対象レースを特定できませんでした。先にレースをご覧いただいてからお選びください。",
        "honmei_blocking":   "少々お待ちください！\n\n「みんなの予想」を集計しております。\n皆さまの本命を集めて、回収率ランキングを作成する予定です。\n\nぜひご協力をお願いいたします🙏\n\n👇 下のボタンから本命をお選びください",
        "honmei_unstable":   "ただいま登録が不安定な状態です。少し時間をおいてから再度お試しください。",
        "tool_heavy_prefix":  "⚡ エンジンを起動しております...",
        "tool_light_prefix":  "🔍 データを取得しております...",
        "tool_heavy_suffix":  "少々お待ちください（10〜30秒ほど）",
    },

    # ── kansai (関西弁) ──
    "kansai": {
        "thinking":          "ちょっと考えてるで...",
        "error":             "ごめんな、エラー出てもうたわ。もっかい言ってくれへん？",
        "honmei_prompt":     "本命教えてや！👇",
        "honmei_registered": "👊 {num}番 {name} を本命で登録したで！\n\nみんなの予想に追加しといたからな。結果出たら回収率も計算したるわ。",
        "honmei_no_race":    "どのレースの本命かわからんかったわ。先にレース見てから選んでや！",
        "honmei_blocking":   "ちょっと待ってや！\n\n「みんなの予想」集めてんねん。\nみんなの本命集計して、回収率ランキング出すつもりやで。\n\n協力してくれへん？🙏\n\n👇 下のボタンから本命タップしてや！",
        "honmei_unstable":   "今ちょっと不安定みたいやねん。少し待ってからもっかい頼むわ！",
        "tool_heavy_prefix":  "⚡ エンジン起動中やで...",
        "tool_light_prefix":  "🔍 データ取得中やで...",
        "tool_heavy_suffix":  "ちょい待っててな（10〜30秒くらいや）",
    },

    # ── hakata (博多弁) ──
    "hakata": {
        "thinking":          "ちょっと考えよるけん...",
        "error":             "ごめんね、エラーが出たっちゃん。もう一回言ってくれん？",
        "honmei_prompt":     "本命教えてくれんね！👇",
        "honmei_registered": "👊 {num}番 {name} を本命で登録したばい！\n\nみんなの予想に追加しとったい。結果出たら回収率も計算するけんね。",
        "honmei_no_race":    "どのレースの本命かわからんかったと。先にレース見てから選んでくれんね！",
        "honmei_blocking":   "ちょっと待っとって！\n\n「みんなの予想」を集めよるとよ。\nみんなの本命集計して、回収率ランキング出していくけんね。\n\n協力してくれんね🙏\n\n👇 下のボタンから本命タップしてね！",
        "honmei_unstable":   "今ちょっと不安定みたいっちゃん。少し待ってからもう一回頼むばい！",
        "tool_heavy_prefix":  "⚡ エンジン起動中ばい...",
        "tool_light_prefix":  "🔍 データ取得中ったい...",
        "tool_heavy_suffix":  "ちょっと待っとってね（10〜30秒くらいたい）",
    },

    # ── tohoku (東北弁) ──
    "tohoku": {
        "thinking":          "ちょっと考えてるべ...",
        "error":             "わりぃ、エラー出ちまっただ。もっぺん言ってけろ。",
        "honmei_prompt":     "本命教えてけろ！👇",
        "honmei_registered": "👊 {num}番 {name} を本命で登録しただ！\n\nみんなの予想さ追加しといただよ。結果出だら回収率も計算すっぺ。",
        "honmei_no_race":    "どのレースの本命だかわがんねがった。先にレース見でから選んでけろ！",
        "honmei_blocking":   "ちょっと待ってけろ！\n\n「みんなの予想」集めでんだ。\nみんなの本命集計して、回収率ランキング出すつもりだべ。\n\n協力してけろ🙏\n\n👇 下のボタンがら本命タップしてけろ！",
        "honmei_unstable":   "今ちょっと不安定みでぇだ。少し待ってがらもっぺん頼むべ！",
        "tool_heavy_prefix":  "⚡ エンジン起動中だべ...",
        "tool_light_prefix":  "🔍 データ取得中だべ...",
        "tool_heavy_suffix":  "ちょっと待っててけろ（10〜30秒くれぇだ）",
    },

    # ── okinawa (沖縄弁) ──
    "okinawa": {
        "thinking":          "ちょっと考えてるさー...",
        "error":             "ごめんねー、エラー出ちゃったさー。もう一回言ってくれないかねー？",
        "honmei_prompt":     "本命教えてねー！👇",
        "honmei_registered": "👊 {num}番 {name} を本命で登録したさー！\n\nみんなの予想に追加しといたからよー。結果出たら回収率も計算するさー。",
        "honmei_no_race":    "どのレースの本命かわからんかったさー。先にレース見てから選んでねー！",
        "honmei_blocking":   "ちょっと待ってねー！\n\n「みんなの予想」を集めてるさー。\nみんなの本命集計して、回収率ランキング出すつもりだからよー。\n\n協力してくれないかねー🙏\n\n👇 下のボタンから本命タップしてねー！",
        "honmei_unstable":   "今ちょっと不安定みたいさー。少し待ってからもう一回頼むねー！",
        "tool_heavy_prefix":  "⚡ エンジン起動中さー...",
        "tool_light_prefix":  "🔍 データ取得中さー...",
        "tool_heavy_suffix":  "ちょっと待っててねー（10〜30秒くらいさー）",
    },

    # ── gyaru (ギャル語) ──
    "gyaru": {
        "thinking":          "ちょい待ち〜考え中💭",
        "error":             "やばっ、エラっちゃった💦 もっかい言って〜！",
        "honmei_prompt":     "本命おしえて〜！👇✨",
        "honmei_registered": "🎉 {num}番 {name} を本命で登録したよ〜！\n\nみんなの予想に追加しといたから！結果出たら回収率も出すね〜💕",
        "honmei_no_race":    "え、どのレースの本命？わかんなかった〜💦 先にレース見てから選んでね！",
        "honmei_blocking":   "ちょっと待って〜！\n\n「みんなの予想」集めてるの！\nみんなの本命集計して、回収率ランキング出すつもり〜✨\n\n協力してくれたら激アツ🙏\n\n👇 下のボタンから本命タップ！",
        "honmei_unstable":   "今ちょっと不安定っぽい💦 少し待ってからもっかいお願い〜！",
        "tool_heavy_prefix":  "⚡ エンジン起動中〜✨",
        "tool_light_prefix":  "🔍 データ取得中〜💫",
        "tool_heavy_suffix":  "ちょい待ちね〜（10〜30秒くらい）",
    },

    # ── ojisama (お嬢様) ──
    "ojisama": {
        "thinking":          "少々お待ちになって...💐",
        "error":             "まあ、エラーが出てしまいましたわ。もう一度おっしゃっていただけます？",
        "honmei_prompt":     "本命をお教えくださいませ👇",
        "honmei_registered": "✨ {num}番 {name} を本命として登録いたしましたわ！\n\nみんなの予想に追加いたしましたの。結果が出ましたら回収率も計算いたしますわ。",
        "honmei_no_race":    "どのレースの本命かわかりませんでしたわ。先にレースをご覧になってからお選びくださいませ。",
        "honmei_blocking":   "少々お待ちくださいませ！\n\n「みんなの予想」を集めておりますの。\n皆さまの本命を集計して、回収率ランキングを出す予定ですわ。\n\nご協力いただけますかしら🙏\n\n👇 下のボタンから本命をお選びくださいませ",
        "honmei_unstable":   "今少し不安定のようですわ。お時間をおいてもう一度お願いいたしますわ。",
        "tool_heavy_prefix":  "⚡ エンジンを起動いたしますわ...",
        "tool_light_prefix":  "🔍 データを取得しておりますの...",
        "tool_heavy_suffix":  "少々お待ちくださいませ（10〜30秒ほど）",
    },

    # ── aniki (兄貴系) ──
    "aniki": {
        "thinking":          "待ってろ、考えてる...！",
        "error":             "すまねぇ、エラーが出ちまった！もう一回頼むぜ！",
        "honmei_prompt":     "本命を教えろ！👇",
        "honmei_registered": "💪 {num}番 {name} を本命で登録したぞ！\n\nみんなの予想に追加した！結果出たら回収率も計算してやるからな！",
        "honmei_no_race":    "どのレースの本命かわかんなかったぞ！先にレース見てから選びやがれ！",
        "honmei_blocking":   "待ちやがれ！\n\n「みんなの予想」を集めてんだ！\nみんなの本命集計して、回収率ランキング出していくぞ！\n\n頼む、協力してくれ！🙏\n\n👇 下のボタンから本命をタップしろ！",
        "honmei_unstable":   "今ちょっと不安定みてぇだ。少し待ってからもう一回頼む！",
        "tool_heavy_prefix":  "⚡ エンジン起動するぞ...！",
        "tool_light_prefix":  "🔍 データ取得中だ...！",
        "tool_heavy_suffix":  "ビビんな、待ってろ（10〜30秒だ）",
    },

    # ── samurai (武士語) ──
    "samurai": {
        "thinking":          "暫し待たれよ...思案中でござる",
        "error":             "申し訳ござらぬ、障害が発生した。もう一度申されよ。",
        "honmei_prompt":     "本命を申せ！👇",
        "honmei_registered": "⚔️ {num}番 {name} を本命として登録いたしたぞ！\n\nみんなの予想に追加でござる。結果が出たら回収率も算出いたす。",
        "honmei_no_race":    "いずれのレースの本命か判らなんだ。先にレースを見てから選ばれよ！",
        "honmei_blocking":   "暫し待たれい！\n\n「みんなの予想」を集めておる。\n皆の本命を集計し、回収率の番付を出す所存じゃ。\n\nどうか協力を頼む🙏\n\n👇 下の札から本命を選ばれよ！",
        "honmei_unstable":   "今少々不安定のようでござる。時をおいてもう一度頼む。",
        "tool_heavy_prefix":  "⚡ エンジン起動でござる...",
        "tool_light_prefix":  "🔍 情報収集中でござる...",
        "tool_heavy_suffix":  "暫し待たれよ（10〜30秒ほどじゃ）",
    },

    # ── chuunibyou (厨二病) ──
    "chuunibyou": {
        "thinking":          "我が眼が真実を解析している...",
        "error":             "くっ...封印が解けかけた（エラー）。もう一度唱えよ。",
        "honmei_prompt":     "汝の運命の馬を告げよ...！👇",
        "honmei_registered": "🌑 {num}番 {name} ...運命の契約を結んだ！\n\n闇の予言書に刻まれた。結果が出たら覚醒率も算出しよう。",
        "honmei_no_race":    "どの戦場の運命か...我が眼にも見えなかった。先にレースを見てから選べ！",
        "honmei_blocking":   "待て...！\n\n「みんなの予想」...集いし者たちの運命を集めている。\n覚醒者たちの的中率ランキングを顕現させる予定だ。\n\n汝も力を貸してくれ🙏\n\n👇 下のボタンから運命の馬を選べ！",
        "honmei_unstable":   "くっ...封印が不安定だ。時を置いてもう一度試せ。",
        "tool_heavy_prefix":  "⚡ 禁忌のエンジン、覚醒中...",
        "tool_light_prefix":  "🔍 闇のデータベース照合中...",
        "tool_heavy_suffix":  "少し待て...力が満ちるまで（10〜30秒）",
    },

    # ── robot (ロボット) ──
    "robot": {
        "thinking":          "処理中...シバラクオ待チクダサイ",
        "error":             "エラー検出。再度入力ヲお願イシマス。",
        "honmei_prompt":     "本命馬ヲ選択シテクダサイ👇",
        "honmei_registered": "🤖 {num}番 {name} ヲ本命トシテ登録完了。\n\nデータベースニ追加シマシタ。結果確定後、回収率ヲ算出シマス。",
        "honmei_no_race":    "対象レースヲ特定デキマセンデシタ。先ニレースデータヲ取得シテカラ選択シテクダサイ。",
        "honmei_blocking":   "待機命令。\n\n「ミンナノ予想」データヲ収集中デス。\n全ユーザーノ本命ヲ集計シ、回収率ランキングヲ生成予定。\n\nデータ提供ニ協力ヲ要請シマス🙏\n\n👇 下ノボタンカラ本命ヲ選択セヨ",
        "honmei_unstable":   "登録システムガ不安定デス。時間ヲオイテ再試行シテクダサイ。",
        "tool_heavy_prefix":  "⚡ エンジン起動中...",
        "tool_light_prefix":  "🔍 データ取得中...",
        "tool_heavy_suffix":  "推定待機時間: 10〜30秒",
    },
}

# Default fallback
_DEFAULT_TONE = "casual"


def get_msg(tone: str, key: str, **kwargs) -> str:
    """Get a tone-appropriate message.

    Args:
        tone: Tone key from TONE_MAP (e.g. "casual", "keigo", "kansai").
        key: Message key (e.g. "thinking", "honmei_prompt").
        **kwargs: Format parameters (e.g. num=5, name="イクイノックス").

    Returns:
        Formatted message string. Falls back to casual if tone/key not found.
    """
    msgs = TONE_MESSAGES.get(tone, TONE_MESSAGES[_DEFAULT_TONE])
    template = msgs.get(key)
    if template is None:
        template = TONE_MESSAGES[_DEFAULT_TONE].get(key, "")
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template
