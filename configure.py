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

BEGIN = b'<!-- aIKnownOfYou:begin -->'
END = b'<!-- aIKnownOfYou:end -->'
OWNER = '<!-- aIKnownOfYou:setup -->'
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
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ConfigurationError('カタログ形式に互換性がありません。')
    return value


def validate_profile(profile, cat=None):
    # Without a catalog, validate only the fixed payload shape for an upgrade.
    # Do not derive preferences or interpret old answers through a new version.
    if (not isinstance(profile, dict) or not isinstance(profile.get('catalog_version'), str)
            or not profile['catalog_version']
            or (cat is not None and profile['catalog_version'] != cat['version'])):
        raise ConfigurationError('保存設定とカタログのバージョンに互換性がありません。')
    if set(profile) != {'catalog_version', 'answers', 'level', 'evidence'}:
        raise ConfigurationError('入力には所定の4項目だけを指定してください。')
    level = profile.get('level')
    if type(level) is not int or not 80 <= level <= 130:
        raise ConfigurationError('内部設定値が不正です。')
    answers = profile.get('answers')
    questions = ({q['id']: q for q in cat['questions']} if cat is not None else
                 {'q' + str(i): {'choices': [{'id': c, 'preference_ids': []} for c in 'ABCD']}
                  for i in range(1, 9)})
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ConfigurationError('全8問の回答が必要です。')
    special = {c['id'] for c in cat['special_choices']} if cat is not None else {'context', 'none', 'skip'}
    answered = 0
    preferences = []
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
            for choice in selected:
                for pid in choices[choice]['preference_ids']:
                    if pid not in cat['preference_rules']:
                        raise ConfigurationError('カタログの選好ルールが不正です。')
                    if pid not in preferences:
                        preferences.append(pid)
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
    rules = cat['selection_rules'] if cat is not None else {'min_answered': 3, 'fallback_level': 100, 'evidence_min': 2}
    if answered < rules['min_answered']:
        if level != rules['fallback_level']:
            raise ConfigurationError('回答が少ない場合は既定の内部設定を使用してください。')
    elif len(evidence_questions) < rules['evidence_min']:
        raise ConfigurationError('異なる2問以上から選択根拠を示してください。')
    return preferences


def compiled_region(profile, cat):
    preferences = validate_profile(profile, cat)
    level = profile['level']
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
    return BEGIN + b'\n' + ('\n'.join(texts)).encode('utf-8') + b'\n' + END


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
    state = read_json(base / 'state.json', originals)
    if state is None:
        return {'schema_version': 1, 'targets': {}}
    if (not isinstance(state, dict) or state.get('schema_version') != 1
            or not isinstance(state.get('targets'), dict)
            or any(t not in TARGETS or not isinstance(p, str) or not Path(p).is_absolute()
                   for t, p in state['targets'].items())):
        raise ConfigurationError('保存状態の形式に互換性がありません。')
    return state


def plan_instructions(state, cat, changes, originals):
    region = compiled_region(state['profile'], cat)
    state['instruction_paths'] = {}
    for target, location in state['targets'].items():
        path = instruction_path(target, location, originals)
        changes[path] = replace_region(read_bytes(path, originals), region)
        state['instruction_paths'][target] = str(path)


def install(args, home, base, cat, state, originals):
    state = copy.deepcopy(state)
    version_mismatch = False
    if 'profile' in state:
        validate_profile(state['profile'])
        version_mismatch = state['profile']['catalog_version'] != cat['version']
    selected = TARGETS if args.target == 'both' else (args.target,)
    for target in selected:
        explicit = args.codex_home if target == 'codex' else args.claude_home
        environment = os.environ.get('CODEX_HOME' if target == 'codex' else 'CLAUDE_CONFIG_DIR') if args.home is None else None
        default = home / ('.codex' if target == 'codex' else '.claude')
        state['targets'][target] = str(absolute(explicit or state['targets'].get(target) or environment or default))
    runtime = base / 'runtime'
    changes = {runtime / 'configure.py': (SOURCE / 'configure.py').read_bytes(),
               runtime / 'catalog.json': (SOURCE / 'catalog.json').read_bytes()}
    prefix = command_prefix(sys.executable, runtime / 'configure.py', home)
    for target in TARGETS:
        template_path = Path('templates') / target / 'SKILL.md.tmpl'
        changes[runtime / template_path] = (SOURCE / template_path).read_bytes()
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
        plan_instructions(state, cat, changes, originals)
    changes[base / 'state.json'] = json_bytes(state)
    commit_changes(changes, base / 'backups', originals)
    if version_mismatch:
        print('セットアップSkillを更新しました。保存設定とのバージョンが異なるため、明示的な再設定が必要です。')
    else:
        print('セットアップSkillをインストールしました。' + ('保存設定を適用しました。' if 'profile' in state else '質問による初期設定を実行してください。'))


def apply(args, base, cat, state, originals):
    if not state['targets']:
        raise ConfigurationError('先に install を実行してください。')
    state = copy.deepcopy(state)
    if args.input:
        if args.input == '-':
            profile = json.loads(sys.stdin.read().lstrip('\ufeff'))
        else:
            profile = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
        validate_profile(profile, cat)
        # Persist only the fixed payload contract, never arbitrary instructions.
        state['profile'] = {key: profile[key] for key in ('catalog_version', 'answers', 'level', 'evidence')}
    if 'profile' not in state:
        raise ConfigurationError('保存設定がありません。セットアップSkillで質問に回答してください。')
    changes = {}
    plan_instructions(state, cat, changes, originals)
    changes[base / 'state.json'] = json_bytes(state)
    commit_changes(changes, base / 'backups', originals)
    print('インストール済みの全クライアントに設定を適用しました。')


def status(state, cat, home):
    result = {'installed': bool(state['targets']), 'configured': 'profile' in state,
              'catalog_compatible': True, 'needs_apply': False, 'targets': {}}
    region = None
    if result['configured']:
        try:
            region = compiled_region(state['profile'], cat)
        except (ConfigurationError, KeyError, TypeError):
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
            elif content[span[0]:span[1]] != region:
                message = '変更あり'
            else:
                message = '整合'
        except (OSError, ConfigurationError):
            path = Path(location)
            message = '変更または不正なファイル'
        if result['configured'] and message != '整合':
            result['needs_apply'] = True
        skill_home = home / '.agents' if target == 'codex' else Path(location)
        skill = skill_home / 'skills/aiknownofyou-setup/SKILL.md'
        try:
            skill_ok = OWNER.encode() in (read_bytes(skill) or b'')
        except (OSError, ConfigurationError):
            skill_ok = False
        result['targets'][target] = {'instruction_path': str(path), 'status': message,
                                     'skill_installed': skill_ok}
    result['message'] = '設定状態を確認しました。' if result['installed'] else '未インストールです。'
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
                'level': '80〜130の整数。3問未満の通常回答なら100を使用する。',
                'evidence': '実際に選んだ通常の選択肢を {question, choice} で列挙する。通常回答が3問以上なら異なる2問以上必要。'},
                'application': 'UTF-8 JSONを一時ファイルに保存し、apply --input に引用したパスを渡す。自分で作成した一時ファイルのみ削除する。'}, ensure_ascii=False, indent=2))
        elif args.command == 'status':
            status(load_state(base), cat, home)
        else:
            with operation_lock(base):
                originals = {}
                state = load_state(base, originals)
                if args.command == 'install':
                    install(args, home, base, cat, state, originals)
                else:
                    apply(args, base, cat, state, originals)
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
