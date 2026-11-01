#!/usr/bin/env python3
"""aIKnownOfYou: portable, local configuration using the Python standard library."""
import argparse
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import tempfile
import uuid

# Read-only commands must not create __pycache__ in an installed runtime.
sys.dont_write_bytecode = True
from selection import select_profile, validate_catalog, verify_profile

BEGIN = b'<!-- aIKnownOfYou:begin -->'
END = b'<!-- aIKnownOfYou:end -->'
OWNER = '<!-- aIKnownOfYou:setup -->'
DAILY_OWNER = '<!-- aIKnownOfYou:daily -->'
PROFILE_OWNER = '<!-- aIKnownOfYou:profile -->'
TARGETS = ('codex', 'claude-code')
SOURCE = Path(__file__).absolute().parent


class ConfigurationError(Exception):
    pass


def absolute(value):
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def safe_path(path):
    """Refuse symlinks, including parents, rather than replacing their targets."""
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ConfigurationError('シンボリックリンクは更新できません: ' + str(part))
    if path.exists() and not path.is_file():
        raise ConfigurationError('通常ファイルではありません: ' + str(path))
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise ConfigurationError('親ディレクトリが不正です: ' + str(parent))


def read_bytes(path, originals=None):
    safe_path(path)
    content = path.read_bytes() if path.exists() else None
    if originals is not None:
        if path in originals and content != originals[path]:
            raise ConfigurationError('操作中にファイルが変更されました: ' + str(path))
        originals[path] = content
    return content


def read_json(path, originals=None):
    content = read_bytes(path, originals)
    return json.loads(content.decode('utf-8-sig')) if content is not None else None


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def catalog():
    value = read_json(SOURCE / 'catalog.json')
    validate_catalog(value)
    return value


def validate_legacy_profile(profile):
    """Check the known 0.1 shape without interpreting it using new choices."""
    if not isinstance(profile, dict) or profile.get('catalog_version') != '0.1.0':
        raise ConfigurationError('この版の保存設定は読み替えできません。対応する版のツールを使用してください。')
    if set(profile) != {'catalog_version', 'answers', 'level', 'evidence'}:
        raise ConfigurationError('入力には所定の4項目だけを指定してください。')
    level = profile.get('level')
    if type(level) is not int or not 80 <= level <= 130:
        raise ConfigurationError('内部設定値が不正です。')
    answers = profile.get('answers')
    questions = {'q' + str(i): {'choices': [{'id': c} for c in 'ABCD']} for i in range(1, 9)}
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ConfigurationError('全8問の回答が必要です。')
    special = {'context', 'none', 'skip'}
    answered = 0
    for qid, question in questions.items():
        choices = {c['id']: c for c in question['choices']}
        selected = answers[qid]
        if (not isinstance(selected, list) or not 1 <= len(selected) <= 2
                or any(not isinstance(c, str) for c in selected)
                or len(set(selected)) != len(selected)):
            raise ConfigurationError('回答の形式が不正です: ' + qid)
        if selected[0] in special:
            if len(selected) != 1:
                raise ConfigurationError('特別な回答は単独で指定してください: ' + qid)
        else:
            if any(c not in choices for c in selected):
                raise ConfigurationError('未知の選択肢です: ' + qid)
            answered += 1
    evidence = profile.get('evidence')
    if not isinstance(evidence, list):
        raise ConfigurationError('選択根拠の配列が必要です。')
    evidence_questions = set()
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {'question', 'choice'}:
            raise ConfigurationError('選択根拠の形式が不正です。')
        qid, choice = item.get('question'), item.get('choice')
        if (not isinstance(qid, str) or not isinstance(choice, str)
                or qid not in questions or choice not in answers[qid] or choice in special):
            raise ConfigurationError('選択根拠は実際に選んだ通常の回答を指定してください。')
        evidence_questions.add(qid)
    rules = {'min_answered': 3, 'fallback_level': 100, 'evidence_min': 2}
    if answered < rules['min_answered']:
        if level != rules['fallback_level']:
            raise ConfigurationError('回答が少ない場合は既定の内部設定を使用してください。')
    elif len(evidence_questions) < rules['evidence_min']:
        raise ConfigurationError('異なる2問以上から選択根拠を示してください。')


def validate_profile(profile, cat):
    verify_profile(profile, cat)
    preferences = []
    for question in cat['questions']:
        choices = {c['id']: c for c in question['choices']}
        for selected in profile['answers'][question['id']]:
            for preference in choices.get(selected, {}).get('preference_ids', []):
                if preference not in preferences:
                    preferences.append(preference)
    return preferences


def render_instructions(level, preferences, cat):
    """Render all 51 internal integers, independently of selector candidates."""
    if type(level) is not int or not 80 <= level <= 130:
        raise ConfigurationError('内部設定値が不正です。')
    low = level // 10 * 10
    texts = list(cat['common_instructions'])
    if level == low:
        texts.append(cat['level_instructions'][str(low)])
    else:
        upper_weight = level - low
        texts.append('次の2つの指示を記載の重みで組み合わせて適用する。これは指示の補間であり、実証された心理尺度ではない。')
        texts.append('重み ' + str(10 - upper_weight) + '/10: ' + cat['level_instructions'][str(low)])
        texts.append('重み ' + str(upper_weight) + '/10: ' + cat['level_instructions'][str(low + 10)])
    texts.extend(cat['preference_rules'][pid] for pid in preferences)
    return '\n'.join(texts)


def compiled_region(profile, cat):
    preferences = validate_profile(profile, cat)
    return BEGIN + b'\n' + render_instructions(profile['level'], preferences, cat).encode('utf-8') + b'\n' + END


def region_span(content):
    starts, ends = content.count(BEGIN), content.count(END)
    if starts == ends == 0:
        return None
    if starts != 1 or ends != 1 or content.index(BEGIN) >= content.index(END):
        raise ConfigurationError('管理領域のマーカーが不正または重複しています。')
    return content.index(BEGIN), content.index(END) + len(END)


def replace_region(original, region):
    content = original or b''
    span = region_span(content)
    if span:
        return content[:span[0]] + region + content[span[1]:]
    separator = b'' if not content or content.endswith(b'\n') else b'\n'
    return content + separator + region + b'\n'


def instruction_path(target, location, originals=None):
    directory = Path(location)
    if target == 'codex':
        override = directory / 'AGENTS.override.md'
        if read_bytes(override, originals):
            return override
        return directory / 'AGENTS.md'
    return directory / 'CLAUDE.md'


def command_prefix(interpreter, script, home, windows=None):
    args = [str(interpreter), str(script), '--home', str(home)]
    if windows is None:
        windows = os.name == 'nt'
    if windows:
        return '& ' + ' '.join("'" + a.replace("'", "''") + "'" for a in args)
    return ' '.join(shlex.quote(a) for a in args)


@contextmanager
def operation_lock(base):
    lock = base / 'operation.lock'
    safe_path(lock)
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ConfigurationError('別の設定操作が実行中です。operation.lock を確認してください。')
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink()


def stage_file(path, content, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.aiknownofyou-', dir=str(path.parent))
    staged = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(staged, mode)
        return staged
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def commit_changes(changes, backup_dir, originals):
    """Reject stale planning reads before writes; rollback only our unchanged writes."""
    # Unconditional runtime copies have no earlier destination-dependent read.
    # Instructions, ownership, state, and precedence checks retain planning bytes.
    for path in changes:
        if path not in originals:
            originals[path] = read_bytes(path)
    for path, expected in originals.items():
        if read_bytes(path) != expected:
            raise ConfigurationError('操作中にファイルが変更されました: ' + str(path))
    changes = {path: data for path, data in changes.items() if data != originals[path]}
    modes = {path: stat.S_IMODE(path.stat().st_mode) if originals[path] is not None else 0o600
             for path in changes}
    safe_path(backup_dir / 'preflight')
    staged, written = {}, []
    try:
        batch_dir = backup_dir / uuid.uuid4().hex
        manifest = {'files': []}
        for index, (path, data) in enumerate(changes.items()):
            backup_name = str(index) + '-' + path.name + '.bak' if originals[path] is not None else None
            manifest['files'].append({'path': str(path), 'backup': backup_name,
                                      'original_mode': modes[path] if originals[path] is not None else None})
            if backup_name:
                backup = batch_dir / backup_name
                private_snapshot = stage_file(backup, originals[path], 0o600)
                try:
                    os.replace(private_snapshot, backup)
                finally:
                    private_snapshot.unlink(missing_ok=True)
        if changes:
            manifest_path = batch_dir / 'manifest.json'
            private_manifest = stage_file(manifest_path, json_bytes(manifest), 0o600)
            try:
                os.replace(private_manifest, manifest_path)
            finally:
                private_manifest.unlink(missing_ok=True)
        for path, data in changes.items():
            staged[path] = stage_file(path, data, modes[path])
        for path, data in changes.items():
            if read_bytes(path) != originals[path]:
                raise ConfigurationError('操作中にファイルが変更されました: ' + str(path))
            os.replace(staged[path], path)
            written.append(path)
    except BaseException as error:
        conflicts = []
        for path in reversed(written):
            try:
                if read_bytes(path) != changes[path]:
                    conflicts.append(str(path))
                elif originals[path] is None:
                    path.unlink()
                else:
                    restore = stage_file(path, originals[path], modes[path])
                    try:
                        os.replace(restore, path)
                    finally:
                        restore.unlink(missing_ok=True)
            except (OSError, ConfigurationError):
                conflicts.append(str(path))
        if conflicts:
            raise ConfigurationError('更新に失敗しました。外部変更または復元失敗のため要確認: ' + ', '.join(conflicts)) from error
        raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)


def load_state(base, originals=None):
    content = read_bytes(base / 'state.json', originals)
    if content is None:
        return {'schema_version': 1, 'targets': {}}
    state = json.loads(content.decode('utf-8-sig'))
    if (not isinstance(state, dict) or type(state.get('schema_version')) is not int
            or state['schema_version'] != 1
            or not isinstance(state.get('targets'), dict)
            or any(t not in TARGETS or not isinstance(p, str) or not Path(p).is_absolute()
                   for t, p in state['targets'].items())):
        raise ConfigurationError('保存状態の形式に互換性がありません。')
    return state


def owned_change(changes, path, content, owner, originals):
    existing = read_bytes(path, originals)
    if existing is not None and owner.encode('utf-8') not in existing:
        raise ConfigurationError('別のファイルがあるため更新できません: ' + str(path))
    if path in changes and changes[path] != content:
        raise ConfigurationError('異なる対象の保存先が重複しています。')
    changes[path] = content


def codex_daily_files(home, profile, cat):
    daily = home / '.agents/skills/aiknownofyou'
    prefix = command_prefix(sys.executable, home / '.aiknownofyou/runtime/configure.py', home)
    template = (SOURCE / 'templates/codex/daily-SKILL.md.tmpl').read_text(encoding='utf-8')
    skill = template.replace('{{COMMAND}}', prefix)
    if DAILY_OWNER not in skill:
        skill += '\n' + DAILY_OWNER + '\n'
    preferences = validate_profile(profile, cat)
    body = PROFILE_OWNER + '\n# 保存済みの会話方針\n\n'
    body += render_instructions(profile['level'], preferences, cat) + '\n'
    return {daily / 'SKILL.md': skill.encode('utf-8'),
            daily / 'references/profile.md': body.encode('utf-8')}


def codex_loader(home):
    text = ('各ユーザー依頼への応答を組み立てる前に aiknownofyou Skill を使用する。\n'
            'Skill の場所: ' + str(home / '.agents/skills/aiknownofyou/SKILL.md') + '\n'
            '保存済みの会話方針を適用し、初回質問や内部値の入力を通常の会話で繰り返さない。')
    return BEGIN + b'\n' + text.encode('utf-8') + b'\n' + END


def plan_instructions(state, cat, home, changes, originals):
    region = compiled_region(state['profile'], cat)
    state['instruction_paths'] = {}
    state['daily_skill_paths'] = {}
    state['profile_paths'] = {}
    for target, location in state['targets'].items():
        path = instruction_path(target, location, originals)
        if target == 'codex':
            files = codex_daily_files(home, state['profile'], cat)
            for destination, content in files.items():
                owner = DAILY_OWNER if destination.name == 'SKILL.md' else PROFILE_OWNER
                owned_change(changes, destination, content, owner, originals)
            daily = home / '.agents/skills/aiknownofyou'
            state['daily_skill_paths'][target] = str(daily / 'SKILL.md')
            state['profile_paths'][target] = str(daily / 'references/profile.md')
            loader = codex_loader(home)
            # Migrate owned regions in both files so removing an override cannot
            # reactivate a stale personal profile. Preserve all outside bytes.
            for candidate in (Path(location) / 'AGENTS.md', Path(location) / 'AGENTS.override.md'):
                content = read_bytes(candidate, originals)
                if region_span(content or b'') is not None or candidate == path:
                    changes[candidate] = replace_region(content, loader)
        else:
            changes[path] = replace_region(read_bytes(path, originals), region)
        state['instruction_paths'][target] = str(path)


def install(args, home, base, cat, state, originals):
    state = copy.deepcopy(state)
    version_mismatch = False
    if 'profile' in state:
        version_mismatch = state['profile']['catalog_version'] != cat['version']
        if version_mismatch:
            validate_legacy_profile(state['profile'])
        else:
            validate_profile(state['profile'], cat)
    selected = TARGETS if args.target == 'both' else (args.target,)
    for target in selected:
        explicit = args.codex_home if target == 'codex' else args.claude_home
        environment = os.environ.get('CODEX_HOME' if target == 'codex' else 'CLAUDE_CONFIG_DIR') if args.home is None else None
        default = home / ('.codex' if target == 'codex' else '.claude')
        state['targets'][target] = str(absolute(explicit or state['targets'].get(target) or environment or default))
    runtime = base / 'runtime'
    changes = {runtime / 'configure.py': (SOURCE / 'configure.py').read_bytes(),
               runtime / 'selection.py': (SOURCE / 'selection.py').read_bytes(),
               runtime / 'catalog.json': (SOURCE / 'catalog.json').read_bytes()}
    prefix = command_prefix(sys.executable, runtime / 'configure.py', home)
    for target in TARGETS:
        template_path = Path('templates') / target / 'SKILL.md.tmpl'
        changes[runtime / template_path] = (SOURCE / template_path).read_bytes()
    daily_template = Path('templates/codex/daily-SKILL.md.tmpl')
    changes[runtime / daily_template] = (SOURCE / daily_template).read_bytes()
    state['skill_paths'] = {}
    for target, location in state['targets'].items():
        skill_home = home / '.agents' if target == 'codex' else Path(location)
        skill = skill_home / 'skills/aiknownofyou-setup/SKILL.md'
        state['skill_paths'][target] = str(skill)
        existing = read_bytes(skill, originals)
        if existing is not None and OWNER.encode() not in existing:
            raise ConfigurationError('同名の別のSkillがあるため更新できません: ' + str(skill))
        template = changes[runtime / 'templates' / target / 'SKILL.md.tmpl'].decode('utf-8')
        rendered = template.replace('{{COMMAND}}', prefix).replace('{{CATALOG_PATH}}', str(runtime / 'catalog.json')).replace('{{TARGET}}', target)
        # Preserve YAML frontmatter as the first content for Skill discovery.
        if OWNER not in rendered:
            rendered += '\n' + OWNER + '\n'
        generated = rendered.encode('utf-8')
        if skill in changes and changes[skill] != generated:
            raise ConfigurationError('異なる対象のSkill保存先が重複しています。')
        changes[skill] = generated
    if 'profile' in state and not version_mismatch:
        plan_instructions(state, cat, home, changes, originals)
    changes[base / 'state.json'] = json_bytes(state)
    commit_changes(changes, base / 'backups', originals)
    if version_mismatch:
        print('セットアップSkillを更新しました。保存設定とのバージョンが異なるため、明示的な再設定が必要です。')
    else:
        print('セットアップSkillをインストールしました。' + ('保存設定を適用しました。' if 'profile' in state else '質問による初期設定を実行してください。'))


def apply(args, home, base, cat, state, originals):
    if not state['targets']:
        raise ConfigurationError('先に install を実行してください。')
    state = copy.deepcopy(state)
    if args.input:
        if args.input == '-':
            payload = json.loads(sys.stdin.read().lstrip('\ufeff'))
        else:
            payload = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
        state['profile'] = select_profile(payload, cat)
    if 'profile' not in state:
        raise ConfigurationError('保存設定がありません。セットアップSkillで質問に回答してください。')
    changes = {}
    plan_instructions(state, cat, home, changes, originals)
    changes[base / 'state.json'] = json_bytes(state)
    commit_changes(changes, base / 'backups', originals)
    print('インストール済みの全クライアントに設定を適用しました。')


def status(state, cat, home):
    result = {'installed': bool(state['targets']), 'configured': 'profile' in state,
              'catalog_compatible': True, 'needs_apply': False, 'targets': {}}
    region, daily_files = None, {}
    if result['configured']:
        try:
            region = compiled_region(state['profile'], cat)
            if 'codex' in state['targets']:
                daily_files = codex_daily_files(home, state['profile'], cat)
        except (ConfigurationError, OSError, ValueError, KeyError, TypeError):
            result['catalog_compatible'] = False
            result['needs_apply'] = True
    for target, location in state['targets'].items():
        try:
            path = instruction_path(target, location)
            content = read_bytes(path)
            span = region_span(content or b'')
            if not result['configured']:
                message = '未設定'
            elif not result['catalog_compatible']:
                message = '互換性なし'
            elif not span:
                message = '不足'
            elif content[span[0]:span[1]] != (codex_loader(home) if target == 'codex' else region):
                message = '変更あり'
            else:
                message = '整合'
        except (OSError, ConfigurationError):
            path = Path(location)
            message = '変更または不正なファイル'
        skill_home = home / '.agents' if target == 'codex' else Path(location)
        skill = skill_home / 'skills/aiknownofyou-setup/SKILL.md'
        try:
            skill_ok = OWNER.encode() in (read_bytes(skill) or b'')
        except (OSError, ConfigurationError):
            skill_ok = False
        result['targets'][target] = {'instruction_path': str(path), 'status': message,
                                     'skill_installed': skill_ok}
        if target == 'codex':
            daily = home / '.agents/skills/aiknownofyou'
            details = {}
            for name, destination, owner in (
                    ('daily_skill', daily / 'SKILL.md', DAILY_OWNER),
                    ('profile', daily / 'references/profile.md', PROFILE_OWNER)):
                try:
                    actual = read_bytes(destination)
                    present = actual is not None and owner.encode('utf-8') in actual
                    expected = daily_files.get(destination)
                    detail = ('未設定' if not result['configured'] else
                              '互換性なし' if not result['catalog_compatible'] else
                              '不足' if actual is None else
                              '整合' if actual == expected else '変更あり')
                except (OSError, ConfigurationError):
                    present, detail = False, '変更または不正なファイル'
                details[name + '_status'] = detail
                if name == 'daily_skill':
                    details['daily_skill_installed'] = present
                if message == '整合' and detail != '整合':
                    message = detail
            if message == '整合':
                try:
                    for candidate in (Path(location) / 'AGENTS.md', Path(location) / 'AGENTS.override.md'):
                        content = read_bytes(candidate) or b''
                        span = region_span(content)
                        if span is not None and content[span[0]:span[1]] != codex_loader(home):
                            message = '変更あり'
                except (OSError, ConfigurationError):
                    message = '変更または不正なファイル'
            result['targets'][target].update(details)
            result['targets'][target]['status'] = message
        if result['configured'] and message != '整合':
            result['needs_apply'] = True
    result['message'] = '設定状態を確認しました。' if result['installed'] else '未インストールです。'
    print(json.dumps(result, ensure_ascii=False, indent=2))


def explain(state, cat):
    """Explicit, read-only audit. Never create a profile or reinterpret old IDs."""
    if 'profile' not in state:
        result = {'configured': False, 'message': '保存済みの会話設定はありません。'}
    else:
        profile = state['profile']
        if not isinstance(profile, dict):
            raise ConfigurationError('保存プロフィールの形式が不正です。')
        if profile.get('catalog_version') != cat['version']:
            validate_legacy_profile(profile)
            result = {'configured': True, 'verified': False,
                      'catalog_version': profile['catalog_version'], 'level': profile['level'],
                      'method': 'legacy-host-selection', 'answers': profile['answers'],
                      'evidence': profile['evidence'],
                      'message': '旧版では会話中のAIが選定しました。保存値と選択IDのみ表示します。新版の得点・選定理由は復元できません。'}
        else:
            validate_profile(profile, cat)
            reasons = {
                'matched': '同じ重みで加算した得点が単独で最大となり、異なる2問以上の支持もあるため選びました。',
                'adjacent_blend': '隣接する2候補が同じ最大点で、それぞれ異なる2問以上の支持があるため中間の構成を選びました。',
                'mixed': '最大点の候補が隣接する2候補に収まらないため、暫定値を使いました。比較構成への支持が最大という意味ではありません。',
                'insufficient_answers': '通常の選択肢に答えた設問が3問未満のため、暫定値を使いました。',
                'insufficient_support': '最大点の候補の少なくとも一つに、異なる2問以上の支持がないため、暫定値を使いました。'}
            answers = []
            special = {c['id']: c['text'] for c in cat['special_choices']}
            for question in cat['questions']:
                choices = {c['id']: c['text'] for c in question['choices']}
                choices.update(special)
                answers.append({'question': question['id'], 'text': question['text'],
                                'selected': [{'choice': c, 'text': choices[c]}
                                             for c in profile['answers'][question['id']]]})
            result = {'configured': True, 'verified': True, 'catalog_version': profile['catalog_version'],
                      'level': profile['level'], 'reason_message': reasons[profile['selection']['reason']],
                      'selection': profile['selection'], 'answers': answers,
                      'interpretation': '再計算で保存内容との一致を確認しました。規則は独自の暫定設定で、IQ・能力や本人への適合性を検証した値ではありません。'}
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description='aIKnownOfYou ローカル設定')
    parser.add_argument('--home', help='隔離するユーザーホームの絶対パス')
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('install')
    setup.add_argument('--target', choices=(*TARGETS, 'both'), default='both')
    setup.add_argument('--codex-home')
    setup.add_argument('--claude-home')
    commands.add_parser('questions')
    commands.add_parser('guide')
    application = commands.add_parser('apply')
    application.add_argument('--input', help='UTF-8 JSONファイル、または標準入力の -')
    commands.add_parser('status')
    commands.add_parser('explain', help='内部値・選定理由・回答を読み取り専用で確認する')
    args = parser.parse_args(argv)
    try:
        home = absolute(args.home if args.home is not None else Path.home())
        base = home / '.aiknownofyou'
        cat = catalog()
        if args.command == 'questions':
            for question in cat['questions']:
                print(question['id'] + ': ' + question['text'])
                for choice in question['choices'] + cat['special_choices']:
                    print('  ' + choice['id'] + ': ' + choice['text'])
        elif args.command == 'guide':
            print(json.dumps({'catalog': cat, 'apply_payload_contract': {
                'catalog_version': cat['version'],
                'answers': '全8問のIDをキーとし、通常の選択肢1つと任意の異なる第2候補、または特別な選択肢1つを配列で指定する。',
                },
                'selection': '入力は上記2項目のみ。数値と選定理由はプログラムが計算する。level、evidence、selectionを入力に含めない。',
                'application': 'UTF-8 JSONを一時ファイルに保存し、apply --input に引用したパスを渡す。自分で作成した一時ファイルのみ削除する。'}, ensure_ascii=False, indent=2))
        elif args.command == 'status':
            status(load_state(base), cat, home)
        elif args.command == 'explain':
            explain(load_state(base), cat)
        else:
            with operation_lock(base):
                originals = {}
                state = load_state(base, originals)
                if args.command == 'install':
                    install(args, home, base, cat, state, originals)
                else:
                    apply(args, home, base, cat, state, originals)
        return 0
    except (ConfigurationError, OSError, ValueError, KeyError, TypeError) as error:
        print('エラー: ' + str(error), file=sys.stderr)
        return 1


def configure_cli_streams():
    """The executable accepts and emits UTF-8, regardless of inherited locale."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            reconfigure(encoding='utf-8', errors='strict')


if __name__ == '__main__':
    configure_cli_streams()
    sys.exit(main())
