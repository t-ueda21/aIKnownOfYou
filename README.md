# aIKnownOfYou

**最初の質問で考え方の好みを知り、その人に合いそうな会話の進め方をCodex・Claude Codeに保存する、小さな設定ツール。**

名前には「私（aI）はあなたのことを知ってるよ」という気持ちを込めています。

8つの選択式質問に答えると、利用中のAIが会話指示を選びます。内部の数値設定を利用者が操作する必要はありません。保存後は新しい会話から、各製品の個人用指示として使います。

## できること

- 初回の選択式質問から、会話の進め方を設定する。
- CodexとClaude Codeで、同じ質問結果と会話方針を使う。
- 設定をやり直すと、aIKnownOfYouが管理する指示だけを更新する。
- AIの正確さ、必要な論点・条件・例外、コードや検証の品質を維持するよう共通指示を含める。

質問は「情報が足りないとき、まず何をするか」「複雑な問題をどこから考えるか」など、場面に対する選択です。文章の長さ、語彙、丁寧さ、誤字、返信速度から設定を推測しません。

## はじめる

### 1. インストール

前提はGit、Python 3.10以上、利用するCodexまたはClaude Codeです。Pythonの追加パッケージは不要です。

**Windows PowerShell**

```powershell
git clone https://github.com/t-ueda21/aIKnownOfYou.git
cd aIKnownOfYou
py -3 configure.py install --target both
```

**macOS / Linux / WSL**

```sh
git clone https://github.com/t-ueda21/aIKnownOfYou.git
cd aIKnownOfYou
python3 configure.py install --target both
```

使うAIが片方だけなら、最後の引数を変更します。

| 利用するAI | 引数 |
| --- | --- |
| Codex | `--target codex` |
| Claude Code | `--target claude-code` |
| 両方 | `--target both` |

VS CodeでWSLやDev Containerを使う場合は、AIが実行される環境でインストールしてください。Windows側とWSL側の設定は別です。インストールに使ったPythonを移動・削除した場合は、新しいPythonで再インストールしてください。

### 2. 初回設定Skillを使う

インストール後、利用するAIで新しい会話を開き、次を入力します。

**Codex**

```text
$aiknownofyou-setup
```

**Claude Code**

```text
/aiknownofyou-setup
```

提示された8問に、近い選択肢で答えます。基本は1つ、迷う場合は2つまで選べます。「場面による」「近いものがない」「回答しない」も選べます。長文での説明は必要ありません。

AIが選択結果を保存できたことを確認したら、新しい会話を開いて普段どおりに使います。毎回Skillを呼び出したり、内部の数値を指定したりする必要はありません。

### 3. 設定をやり直す

初回設定Skillを呼び出し、「質問から会話設定をやり直して」と伝えます。

保存済みの設定があり、やり直しを求めていない場合は、回答し直さず既存設定を再適用します。後からもう片方のAIを追加するときも、同じリポジトリで対象を指定してインストールすれば、同じ版の保存済み設定を再利用できます。

通常の会話で「今回はもっと具体的に」と伝えることもできます。その依頼だけで保存済みの設定を変更する仕組みにはしていません。

## どこに保存するか

既定の配置先は次のとおりです。`~` はAIを実行する環境のユーザーホームです。

| 場所 | 内容 |
| --- | --- |
| `~/.aiknownofyou/runtime/` | 設定スクリプト、共通定義、Skillのひな形 |
| `~/.aiknownofyou/state.json` | 回答の選択ID、選ばれた内部設定、定義の版、適用先 |
| `~/.aiknownofyou/backups/` | 更新前のファイルと復旧用の記録 |
| `~/.agents/skills/aiknownofyou-setup/SKILL.md` | Codex用の初回設定Skill |
| `~/.codex/AGENTS.md` | Codex用の会話指示。優先されるoverrideファイルがある場合はそちら |
| `~/.claude/skills/aiknownofyou-setup/SKILL.md` | Claude Code用の初回設定Skill |
| `~/.claude/CLAUDE.md` | Claude Code用の会話指示 |

通常の導入では`CODEX_HOME`と`CLAUDE_CONFIG_DIR`による配置先の変更を考慮します。個人用指示には次の区切りを付け、その範囲だけを管理します。

```markdown
<!-- aIKnownOfYou:begin -->
その人向けに組み立てた会話指示
<!-- aIKnownOfYou:end -->
```

質問の全候補や個人の回答は、日常会話用の指示には含めません。保存データは暗号化されないローカルファイルです。初回の回答自体は利用中のAIとの会話で扱われます。設定スクリプトは外部APIへ送信しません。

## 内部の仕組み

1. 初回設定Skillが共通の質問を提示する。
2. 利用中のAIが、選んだ回答だけを根拠に内部Lと根拠の選択IDを決める。
3. スクリプトが入力と根拠の対応を検証する。
4. 共通の品質ルール、Lに対応する会話指示、選択肢に対応する補助指示を組み立てる。
5. 保存した結果を、インストール済みのAIの個人用指示ファイルに反映する。

内部Lは80〜130の整数です。80・90・100・110・120・130の指示を基点とし、中間値では隣接する指示を比重付きで組み合わせます。有効な回答が3問未満の場合は、運用上の初期設定として100を使います。

**これは回答に合いそうな指示を選ぶ初版であり、IQ測定や能力診断ではありません。** 数値1点ごとの体感差や、質問による選択の適合性は未検証です。選択結果は保存して使い続け、普段の会話から自動的に再推定しません。

個人用指示はAIへの文脈として読み込まれます。回答への反映や本人にとっての話しやすさは、ファイルを保存できたこととは別に確認する必要があります。

## Lと質問の対応を見直す設計案

[Lと初回質問の再設計案](docs/level-design-v02.md)に、同じ相談への6種類の完全な回答例、8問の選択肢との対応表、選定理由の記録方法、計算の確認例をまとめています。

これは実装前の設計案です。現在のプログラムは上記の0.1.0の仕組みで動き、この文書の追加で保存済みの設定は変わりません。設計上の計算が再現できることと、本人に合う応答を選べることは別に検証します。

## 開発者向け

### ファイル構成

| ファイル | 役割 |
| --- | --- |
| `catalog.json` | 固定質問、選択肢、選択ルール、Lの指示、共通品質ルール |
| `configure.py` | 導入、入力検証、指示生成、保存、状態確認 |
| `templates/codex/SKILL.md.tmpl` | Codex用Skillの生成元 |
| `templates/claude-code/SKILL.md.tmpl` | Claude Code用Skillの生成元 |
| `tests/test_configure.py` | 既存ファイルの保持、再適用、検証・保存処理のテスト |

### コマンド

| コマンド | 用途 |
| --- | --- |
| `install --target both` | 共通プログラムとSkillを導入する |
| `questions` | 質問と選択肢を表示する |
| `guide` | 初回設定AI向けの定義と入力形式をJSONで表示する |
| `apply --input <JSONファイル>` | AIが作った選択結果を検証して保存する |
| `apply` | 保存済みの設定を再適用する |
| `status` | 導入・設定・指示ファイルの整合状態をJSONで表示する |

`guide`と入力JSONは、初回設定Skillが扱う内部の形式です。一般の利用者が作成する必要はありません。

### 隔離した動作確認

`--home`をコマンドの前に付けると、指定フォルダを仮のユーザーホームにできます。明示的な`--home`使用時は、実環境の構成ディレクトリ用環境変数を引き継ぎません。

```sh
python3 configure.py --home /tmp/aiknownofyou-demo install --target both
python3 configure.py --home /tmp/aiknownofyou-demo status
python3 -m unittest discover -s tests -v
```

インストール済みプログラムは、元のソースフォルダに依存せず、その`runtime/`内の定義を読みます。

設問・指示・選択ルールを変更するときは、`catalog.json`の`version`も更新してください。更新版をインストールしても、異なる版の回答を自動では読み替えません。既存の回答と適用済みの個人用指示を保持したまま設定ツールを更新し、`status`に再設定が必要な状態を表示します。更新後のSkillに「質問から会話設定をやり直して」と依頼し、新しい質問に答えてください。

### 検証範囲と復旧

Linux / Python 3.12で、CLIと一時ホームを使ったテストを実行しています。実際のカタログから両クライアント向けに保存する流れと、生成済みSkillを別のAIが読んで架空の回答から設定する流れも確認しています。CLIの入出力はUTF-8です。利用者のWindows・VS CodeでのSkill検出や、新しい会話での回答への反映は別途確認が必要です。PowerShell向けの引用処理はテストしていますが、Windows実機では実行していません。

捕捉できた書き込み失敗では、この操作が変更したファイルを復元します。更新の途中で別の編集が入ったファイルは上書きせず、エラーとして報告します。強制終了や電源断に対する複数ファイル全体の原子的な更新は保証していません。

異常終了した場合は、まず`status`で各ファイルの状態を確認してください。更新前の記録は`backups/`の各バッチにあり、`manifest.json`で元の絶対パスとバックアップを対応づけられます。`operation.lock`が残っている場合は、別の設定処理が動いていないことを確認してから削除し、再適用してください。自動復元コマンドはありません。

### 公式仕様の参照先

- [Codex: Skills](https://learn.chatgpt.com/docs/build-skills)
- [Codex: AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Claude Code: Skills](https://code.claude.com/docs/en/skills)
- [Claude Code: Memory / CLAUDE.md](https://code.claude.com/docs/en/memory)
- [Claude Code: Environment variables](https://code.claude.com/docs/en/env-vars)
