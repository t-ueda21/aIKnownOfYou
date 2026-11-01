# aIKnownOfYou

**初回の8問で選んだ「考える足場」を、Codexの説明方針として保存する、小さな設定ツール。**

名前には「私（aI）はあなたのことを知ってるよ」という気持ちを込めています。

現行カタログは **0.2.0** です。短い場面ごとの選択をプログラムが固定の規則で集計し、説明の入口と組み立て方を決めます。同じ版と回答なら同じ結果になります。利用者が毎回数値を指定する必要はありません。

## できること

- 初回の8問から、保存して使う説明方針を設定する。
- Codexの初回設定Skillと日常用Skillを分け、通常の会話では保存済み方針を読む。
- 明示的な再設定で質問をやり直し、管理している指示だけを更新する。
- 選定理由を求められたとき、実際の回答と計算結果から説明する。
- どの設定でも正確さ、必要な論点・条件・例外、実装や検証の品質を維持するよう共通指示を含める。

質問は「情報が足りないとき、何を足場にするか」「複雑な問題をどこから考えるか」など、考え方・直感に関する場面選択です。長文の自己説明や知識試験は求めません。文章の長さ、語彙、丁寧さ、誤字、返信速度、経歴、通常のチャットから設定を推測しません。

説明方針の選び方は製品独自の暫定規則です。本人への適合、理解の改善、IQ・知能・能力・性格の測定を実証したものではありません。

## Codexではじめる

### 1. インストール

前提はGit、Python 3.10以上、利用するCodexです。Pythonの追加パッケージ、MCP、サーバー、データベース、追加のモデルAPIは不要です。

**Windows PowerShell**

```powershell
git clone https://github.com/t-ueda21/aIKnownOfYou.git
cd aIKnownOfYou
py -3 configure.py install --target codex
```

**macOS / Linux / WSL**

```sh
git clone https://github.com/t-ueda21/aIKnownOfYou.git
cd aIKnownOfYou
python3 configure.py install --target codex
```

このREADMEではCodexを明示して導入します。`--target`を省いた場合の既定値は、従来どおり`both`です。すでに導入した対象は、別の対象を指定しても削除しません。

| 利用するAI | 引数 |
| --- | --- |
| Codex | `--target codex` |
| Claude Code | `--target claude-code` |
| 両方 | `--target both` |

VS CodeでWSLやDev Containerを使う場合は、AIが実行される環境でインストールしてください。Windows側とWSL側の設定は別です。インストールに使ったPythonを移動・削除した場合は、新しいPythonで再インストールしてください。

### 2. 初回設定Skillで答える

インストール後、Codexで新しい会話を開き、次を入力します。

```text
$aiknownofyou-setup
```

8問それぞれに、A〜Fのうち最も近いものを一つ選びます。次に近いものがあれば二つ目も選べます。二つ選ぶ場合は、より近いものを先にしてください。理由を書く必要はありません。

「状況によって変わる」「どれも当てはまらない」「回答を見送る」も選べます。この三つは他の選択肢と組み合わせず、一つで答えます。未回答を自動的に「回答を見送る」へ変換することはしません。

設定Skillは回答をプログラムへ渡します。AIが内部の数値や選定理由を作る処理はありません。保存後は、ファイルの整合を確認したうえで、新しい会話で使います。

### 3. 日常用Skillで使う

設定後のCodexでは、次の二つのSkillを使い分けます。

| Skill | 役割 |
| --- | --- |
| `aiknownofyou-setup` | 初回質問、再適用、明示的な再設定、選定理由の確認 |
| `aiknownofyou` | 保存済みプロフィールを読み、今回の依頼への説明方針として使う |

Codexの個人用`AGENTS.md`には、「各依頼に応答する前に日常用Skillを使う」という短い呼び出し指示を置きます。方針の本文は日常用Skillの`references/profile.md`へ保存します。通常の会話では初回質問や数値入力を繰り返さず、このツールのためにPythonや設定コマンドを実行しない指示にしています。

日常用Skillを明示的に呼ぶ場合は、`$aiknownofyou`を使えます。毎回の手動指定を前提にした設計ではありません。ただし、呼び出し指示の保存と、Codexが各応答で実際にSkillを読むことは別です。利用者のPC・VS Codeでの読み込みと応答への反映は未確認です。

### 4. 再設定する・理由を確認する

質問からやり直す場合は、`$aiknownofyou-setup`を呼び出し、「質問から会話設定をやり直して」と伝えてください。同じ版の設定があり、やり直しを求めていない場合は、質問を繰り返さず保存済み設定を再適用します。

「今回はもっと具体的に」など、その場の依頼は今回の応答に反映します。その依頼や通常の会話から、保存済みの回答や設定を自動で変更しません。

設定の理由や内部値を知りたい場合は、その確認を明示的に依頼してください。Skillは読み取り専用の`explain`を使い、回答、得点、支持した設問、同点や材料不足の理由を確認します。`explain`の確認だけで再設定は行いません。通常の応答、設定完了メッセージ、`status`には内部値や回答一覧を表示しません。

## 0.1.0から更新する場合

更新したソースで、インストールコマンドをもう一度実行します。

```sh
python3 configure.py install --target codex
```

Windows PowerShellでは`py -3 configure.py install --target codex`を使います。有効な0.1.0の保存設定がある場合、共通プログラムと初回設定Skillを更新し、旧プロフィールと適用済みの個人用指示は保持します。旧A〜Dの回答を新A〜Fへ読み替えたり、保存値を新しい式で再計算したりはしません。

`status`は版の不一致を示します。`$aiknownofyou-setup`に明示的に再設定を依頼し、新しい8問×6択へ答えたときに、0.2.0のプロフィールと日常用Skillの構成へ移ります。旧設定のまま`apply`だけを実行して新方式へ移すことはできません。

旧版に対する`explain`では、保存されている旧値・回答ID・旧根拠だけを表示します。新しい得点や理由は作りません。対応していない版や不正な保存形式はエラーとして扱います。

## どこに保存するか

既定の配置先は次のとおりです。`~`はAIを実行する環境のユーザーホームです。

| 場所 | 内容 |
| --- | --- |
| `~/.aiknownofyou/runtime/` | 設定・選定スクリプト、カタログ、Skillのひな形 |
| `~/.aiknownofyou/state.json` | 回答ID、版、内部値、選定理由・得点・寄与、適用先 |
| `~/.aiknownofyou/backups/` | 更新前のファイルと復旧用の記録 |
| `~/.agents/skills/aiknownofyou-setup/SKILL.md` | Codex用の初回設定Skill |
| `~/.agents/skills/aiknownofyou/SKILL.md` | Codex用の日常Skill |
| `~/.agents/skills/aiknownofyou/references/profile.md` | 共通品質条件、選ばれた構成、回答由来の補助指示 |
| `~/.codex/AGENTS.md` | 日常用Skillを使う短い呼び出し指示。優先されるoverrideファイルがある場合はそちら |
| `~/.claude/skills/aiknownofyou-setup/SKILL.md` | Claude Code用の初回設定Skill |
| `~/.claude/CLAUDE.md` | Claude Code用の会話方針の本文 |

Codexの日常用Skillとプロフィールは、0.2.0の回答を初めて適用した時点で作成します。同じ版のプロフィールがあれば、再インストール時にも再生成します。

通常の導入では、`CODEX_HOME`と`CLAUDE_CONFIG_DIR`による個人用指示の配置先変更を考慮します。CodexのSkillは上表の`~/.agents/skills/`へ置きます。個人用指示には次の区切りを付け、その範囲だけを管理します。

```markdown
<!-- aIKnownOfYou:begin -->
日常用Skillを使う指示（Codex）または会話方針の本文（Claude Code）
<!-- aIKnownOfYou:end -->
```

Codexでは、`AGENTS.md`と`AGENTS.override.md`の双方に以前の管理領域が残っている場合も、0.2.0の適用時に短い指示へ更新します。領域外の個人設定は保持します。

質問の全候補や個人の回答一覧は、日常用プロフィールには含めません。保存データは暗号化されないローカルファイルです。初回の回答自体は利用中のAIとの会話で扱われます。設定スクリプトは外部APIへ送信しません。

## Claude Codeでも使う場合

`install --target claude-code`または`install --target both`で導入し、新しい会話で`/aiknownofyou-setup`を呼び出します。0.2.0ではCodexと同じ回答・選定規則・保存済み方針を使います。同じリポジトリとユーザーホームで後から追加した場合は、同じ版の設定を再利用できます。

Claude Codeへの適用先は従来どおり個人用`CLAUDE.md`です。今回追加した日常用`aiknownofyou` SkillはCodex用です。保存した新しい方針は、そのホームでインストール済みの全対象へ適用します。

## 選び方と根拠

1. 固定8問の回答とカタログの版を受け取る。
2. 一つ選んだ問は3点、二つなら主回答2点・副回答1点を、各選択肢に対応する構成へ加える。
3. 通常回答数、各最大候補を支持した設問数、最大点の同点関係から、構成または暫定値を決める。
4. 回答・内部値・計算過程を保存し、再適用時にも再計算して整合を確認する。
5. 共通品質条件と選んだ構成、必要な補助指示を作り、各対象へ適用する。

各問に六つの構成を一度ずつ置くため、構成ごとの最大点による補正は行いません。質問数や重み、閾値は独自の暫定規則です。構成は具体的な一件、目的と作業群、共通基準での比較、条件の分岐、要素間の関係、捉え方の比較を使い分けます。AIの能力・品質を段階的に下げる指示にはしていません。

内部Lの自動選定は80〜130の11候補です。指示を組み合わせる機構は全51整数を扱えます。これは構成の制御範囲であり、1点単位の人物測定を意味しません。

| 資料 | 内容 |
| --- | --- |
| [0.2.0の選定規則](docs/selection-v02.md) | 正確な質問と対応、式、理由コード、保存形式、手計算例、補助指示の変更 |
| [根拠と背景](docs/evidence-and-design-rationale.md) | 参照した研究の範囲、独自の設計判断、採否、未検証の効果 |
| [6構成の説明例と旧設計案](docs/level-design-v02.md) | 同じ相談への6種類の完全な参照回答と、不採用になった旧計算の履歴 |

旧案の最大点による補正は、共通の支持から分母の差だけで候補を区別する反例があり、採用していません。0.2.0で規則を実装したことと、その規則が本人に合うことを確認したことは区別します。

## 開発者向け

### ファイル構成

| ファイル | 役割 |
| --- | --- |
| `catalog.json` | 固定質問、各選択肢のアンカー、選定規則、構成と共通品質の指示 |
| `selection.py` | 回答だけからの選定、計算過程の作成、保存内容の再計算検証 |
| `configure.py` | 導入、指示生成、保存、状態確認、選定理由の表示 |
| `templates/codex/SKILL.md.tmpl` | Codex用の初回設定Skillの生成元 |
| `templates/codex/daily-SKILL.md.tmpl` | Codex用の日常Skillの生成元 |
| `templates/claude-code/SKILL.md.tmpl` | Claude Code用の初回設定Skillの生成元 |
| `tests/test_selection.py` | 固定選定規則と入力・保存形式の確認 |
| `tests/test_configure.py` | 導入、既存ファイルの保持、再適用、保存・移行・整合状態の確認 |

### コマンド

以下は`python3 configure.py`に続ける引数です。Windowsでは`py -3 configure.py`を使います。

| コマンド | 用途 |
| --- | --- |
| `install --target codex` | 共通プログラムとCodex用設定Skillを導入する |
| `install --target both` | CodexとClaude Codeへ導入する。`--target`省略時も両方 |
| `questions` | 8問とA〜F・特別な選択肢を表示する |
| `guide` | 固定定義と回答のみの入力仕様をJSONで表示する |
| `apply --input <JSONファイル>` | 回答から設定と計算過程を計算・検証して保存する |
| `apply` | 同じ版の保存済み設定を検証して再適用する |
| `status` | 導入・版・設定ファイルの整合状態をJSONで表示する |
| `explain` | 内部値、回答、実際の選定理由を読み取り専用で表示する |

入力JSONのトップレベルは`catalog_version`と`answers`だけです。`level`、`evidence`、`selection`は入力しません。通常は初回設定Skillがこの形式を扱うため、利用者がJSONを作る必要はありません。

`explain`の`verified: true`は、保存した結果が回答からの再計算と一致した意味です。本人への適合を検証した値ではありません。通常の状態確認は`status`を使います。

### 隔離した動作確認

`--home`をコマンドの前に付けると、指定フォルダを仮のユーザーホームにできます。明示的な`--home`使用時は、実環境の構成ディレクトリ用環境変数を引き継ぎません。

```sh
python3 configure.py --home /tmp/aiknownofyou-demo install --target codex
python3 configure.py --home /tmp/aiknownofyou-demo status
python3 -m unittest discover -s tests -v
```

インストール済みプログラムは元のソースフォルダに依存せず、`runtime/`内のスクリプト・定義・ひな形を使います。設問・指示・対応を変更するときは、`catalog.json`の`version`も更新してください。保存形式と選定規則は[0.2.0の選定規則](docs/selection-v02.md)に記載しています。

### 検証範囲と復旧

今回の隔離環境では、次の範囲を確認しています。

| 対象 | 確認した範囲 |
| --- | --- |
| 実カタログとCLI | 六つのアンカー、隣接同点、混在、通常回答不足の代表入力による選定 |
| 旧版からの更新 | 0.1.0の実際の導入処理で作ったプロフィールとCodex・Claudeの指示の保持、明示的な再設定での移行 |
| 初回設定Skill | 独立したエージェントが生成済みSkillと架空回答から設定し、通常の完了表示へ内部値を出さないこと |
| 日常用Skill | 別のエージェントがSkillとプロフィールを読んで一つのCSV設計課題へ回答し、その間の保存ファイルが変化しないこと |

エージェントが生成ファイルを読んだ確認と、実際のCodexホストが毎回自動でSkillを使うことは別です。利用者のPCへのインストール、Windows・VS CodeでのSkill検出、Codexの各応答での読み込み、本人の理解・品質・速度への効果は未確認です。

捕捉できた書き込み失敗では、この操作が変更したファイルを復元します。更新の途中で別の編集が入ったファイルは上書きせず、エラーとして報告します。強制終了や電源断に対する複数ファイル全体の原子的な更新は保証していません。

異常終了した場合は、まず`status`で各ファイルの状態を確認してください。更新前の記録は`backups/`の各バッチにあり、`manifest.json`で元の絶対パスとバックアップを対応づけられます。`operation.lock`が残っている場合は、別の設定処理が動いていないことを確認してから削除し、再適用してください。自動復元コマンドはありません。

### 公式仕様の参照先

- [Codex: Skills](https://learn.chatgpt.com/docs/build-skills)
- [Codex: AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Claude Code: Skills](https://code.claude.com/docs/en/skills)
- [Claude Code: Memory / CLAUDE.md](https://code.claude.com/docs/en/memory)
- [Claude Code: Environment variables](https://code.claude.com/docs/en/env-vars)
