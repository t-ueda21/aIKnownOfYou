"""Behavior tests. Every invocation supplies an isolated --home."""
import contextlib
import copy
import importlib.util
import io
import json
import os
import runpy
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BEGIN = b'<!-- aIKnownOfYou:begin -->'
END = b'<!-- aIKnownOfYou:end -->'


def fixture_catalog():
    return {'schema_version': 1, 'version': '0.2.0',
            'questions': [{'id': 'q' + str(i), 'text': 'Question ' + str(i),
                           'choices': [{'id': c, 'text': c, 'anchor': anchor,
                                        'preference_ids': ['prefer_' + c]}
                                       for c, anchor in zip('ABCDEF', range(80, 131, 10))]} for i in range(1, 9)],
            'special_choices': [{'id': c, 'text': c} for c in ['context', 'none', 'skip']],
            'selection_rules': {'algorithm': 'balanced-choice-v1', 'min_answered': 3,
                                'min_support': 2, 'fallback_level': 100,
                                'single_weight': 3, 'primary_weight': 2, 'secondary_weight': 1},
            'level_instructions': {str(i): 'anchor_' + str(i) for i in range(80, 131, 10)},
            'preference_rules': {'prefer_' + c: 'rule_' + c for c in 'ABCDEF'},
            'common_instructions': ['Preserve quality.']}


def payload(level=105):
    # Hand-derived, distinct answer sets. No caller-supplied level reaches the CLI.
    letters = {80: 'AAAAAAAA', 90: 'BBBBBBBB', 100: 'CCCCCCCC', 105: 'CCCCDDDD',
               110: 'DDDDDDDD', 115: 'DDDDEEEE', 120: 'EEEEEEEE', 130: 'FFFFFFFF'}[level]
    return {'catalog_version': '0.2.0',
            'answers': {'q' + str(i): [c] for i, c in enumerate(letters, 1)}}


def legacy_profile():
    return {'catalog_version': '0.1.0',
            'answers': {'q' + str(i): ['A'] for i in range(1, 9)},
            'level': 105, 'evidence': [{'question': 'q1', 'choice': 'A'}, {'question': 'q2', 'choice': 'A'}]}


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / 'user 日本 space'
        self.source = self.base / 'checkout'
        self.source.mkdir()
        self.assertTrue((ROOT / 'configure.py').exists(), 'configuration engine is not implemented')
        shutil.copyfile(ROOT / 'configure.py', self.source / 'configure.py')
        shutil.copyfile(ROOT / 'selection.py', self.source / 'selection.py')
        (self.source / 'catalog.json').write_text(json.dumps(fixture_catalog()), encoding='utf-8')
        for target in ['codex', 'claude-code']:
            directory = self.source / 'templates' / target
            directory.mkdir(parents=True)
            (directory / 'SKILL.md.tmpl').write_text('---\nname: aiknownofyou-setup\n---\n{{COMMAND}} guide\n{{CATALOG_PATH}}\n{{TARGET}}\n', encoding='utf-8')
        (self.source / 'templates/codex/daily-SKILL.md.tmpl').write_text(
            '---\nname: aiknownofyou\n---\nRead references/profile.md.\n{{COMMAND}} explain\n', encoding='utf-8')

    def run_cli(self, *args, ok=True, script=None, env=None, input_text=None):
        result = subprocess.run([sys.executable, str(script or self.source / 'configure.py'),
                                 '--home', str(self.home), *map(str, args)], text=True,
                                capture_output=True, cwd=self.base, env=env, input=input_text)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result

    def apply(self, data=None, ok=True, script=None):
        path = self.base / 'profile.json'
        path.write_text(json.dumps(data if data is not None else payload()), encoding='utf-8')
        return self.run_cli('apply', '--input', path, ok=ok, script=script)

    def state(self):
        return json.loads((self.home / '.aiknownofyou/state.json').read_text())

    def test_explain_unconfigured_does_not_create_home(self):
        result = json.loads(self.run_cli('explain').stdout)
        self.assertFalse(result['configured'])
        self.assertFalse(self.home.exists())

    def test_apply_creates_codex_daily_skill_and_keeps_profile_out_of_agents(self):
        self.run_cli('install', '--target', 'codex')
        self.apply()
        daily = self.home / '.agents/skills/aiknownofyou'
        self.assertTrue((daily / 'SKILL.md').is_file())
        profile = (daily / 'references/profile.md').read_bytes()
        self.assertIn(b'anchor_100', profile)
        self.assertIn(b'anchor_110', profile)
        agents = (self.home / '.codex/AGENTS.md').read_bytes()
        self.assertNotIn(b'anchor_', agents)
        self.assertIn(str(daily / 'SKILL.md').encode(), agents)
        self.assertTrue(json.loads(self.run_cli('status').stdout)['targets']['codex']['daily_skill_installed'])

    def test_install_is_self_contained_and_defaults_to_both(self):
        self.home = self.base / "user's 日本 space"
        self.run_cli('install')
        runtime = self.home / '.aiknownofyou/runtime'
        self.assertTrue((runtime / 'templates/codex/SKILL.md.tmpl').is_file())
        self.assertEqual(set(self.state()['targets']), {'codex', 'claude-code'})
        skills = [self.home / '.agents/skills/aiknownofyou-setup/SKILL.md',
                  self.home / '.claude/skills/aiknownofyou-setup/SKILL.md']
        commands = [skill.read_text(encoding='utf-8').splitlines()[3] for skill in skills]
        expected = [sys.executable, str(runtime / 'configure.py'), '--home', str(self.home)]
        shutil.rmtree(self.source)
        for skill, command in zip(skills, commands):
            with self.subTest(skill=str(skill)):
                if os.name == 'nt':
                    # PowerShell is not POSIX: keep its invocation operator and
                    # doubled apostrophes, then execute the actual generated line.
                    quoted = ' '.join("'" + part.replace("'", "''") + "'" for part in expected)
                    self.assertEqual(command, '& ' + quoted + ' guide')
                    shell = shutil.which('pwsh') or shutil.which('powershell')
                    self.assertIsNotNone(shell, 'PowerShell is required to verify the Windows Skill command')
                    utf8 = '$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); '
                    invocation = [shell, '-NoLogo', '-NoProfile', '-NonInteractive',
                                  '-Command', utf8 + command + '; exit $LASTEXITCODE']
                else:
                    self.assertEqual(shlex.split(command), expected + ['guide'])
                    invocation = ['/bin/sh', '-c', command]
                result = subprocess.run(invocation, cwd=self.base, capture_output=True,
                                        text=True, encoding='utf-8', timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)['catalog'], fixture_catalog())
        self.run_cli('install', script=runtime / 'configure.py')

    def test_apply_preserves_bytes_and_interpolates_without_exposing_level(self):
        self.run_cli('install')
        agents = self.home / '.codex/AGENTS.md'
        original = b'\xef\xbb\xbfPersonal\r\nJapanese \xe6\x97\xa5\xe6\x9c\xac'
        agents.parent.mkdir(parents=True, exist_ok=True)
        agents.write_bytes(original)
        out = self.apply()
        content = agents.read_bytes()
        self.assertTrue(content.startswith(original))
        profile = (self.home / '.agents/skills/aiknownofyou/references/profile.md').read_bytes()
        self.assertIn(b'anchor_100', profile)
        self.assertIn(b'anchor_110', profile)
        self.assertIn(b'5/10', profile)
        self.assertEqual(profile.count(b'rule_C'), 1)
        self.assertNotIn(b'105', profile)
        self.assertNotIn('105', out.stdout)
        self.run_cli('apply')
        self.assertEqual(agents.read_bytes(), content)
        self.assertEqual(content.count(BEGIN), 1)
        self.assertTrue(list((self.home / '.aiknownofyou/backups').rglob('*')))

    def test_replaces_region_preserving_exact_outside_bytes(self):
        self.run_cli('install', '--target', 'codex')
        path = self.home / '.codex/AGENTS.md'
        prefix, suffix = b'\xef\xbb\xbfkeep\r\n', b'\r\nafter-no-newline'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(prefix + BEGIN + b'old' + END + suffix)
        self.apply()
        actual = path.read_bytes()
        self.assertTrue(actual.startswith(prefix + BEGIN))
        self.assertTrue(actual.endswith(END + suffix))

    def test_rejects_invalid_profile_without_mutation(self):
        self.run_cli('install')
        self.apply()
        cases = []
        for value in [True, 79, 131, 100.0, '100']:
            data = payload(); data['level'] = value; cases.append(data)
        data = payload(); del data['answers']['q8']; cases.append(data)
        data = payload(); data['answers']['q1'] = ['Z']; cases.append(data)
        data = payload(); data['answers']['q1'] = ['A', 'A']; cases.append(data)
        data = payload(); data['answers']['q1'] = ['skip', 'A']; cases.append(data)
        data = payload(); data['selection'] = {}; cases.append(data)
        data = payload(); data['evidence'] = []; cases.append(data)
        data = payload(); data['catalog_version'] = 'future'; cases.append(data)
        before = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        for data in cases:
            with self.subTest(data=data): self.apply(data, ok=False)
        after = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_rejects_extra_payload_or_evidence_fields(self):
        self.run_cli('install')
        data = payload(); data['invented_trait'] = 'unsupported'
        self.apply(data, ok=False)
        data = payload(); data['evidence'] = [{'invented_trait': 'unsupported'}]
        self.apply(data, ok=False)

    def test_bom_payload_and_state_are_readable(self):
        self.run_cli('install')
        path = self.base / 'bom.json'
        path.write_text(json.dumps(payload()), encoding='utf-8-sig')
        self.run_cli('apply', '--input', path)
        state = self.home / '.aiknownofyou/state.json'
        state.write_bytes(b'\xef\xbb\xbf' + state.read_bytes())
        self.run_cli('status')
        self.run_cli('apply')

    def test_backup_manifest_maps_absolute_originals_to_private_snapshots(self):
        self.run_cli('install'); self.apply(); self.apply(payload(115))
        manifests = list((self.home / '.aiknownofyou/backups').rglob('manifest.json'))
        self.assertTrue(manifests)
        entries = [entry for path in manifests for entry in json.loads(path.read_text())['files']]
        state_entries = [entry for entry in entries if entry['path'] == str(self.home / '.aiknownofyou/state.json')]
        self.assertTrue(state_entries)
        for path in manifests:
            for entry in json.loads(path.read_text())['files']:
                self.assertTrue(Path(entry['path']).is_absolute())
                if entry['backup'] is not None:
                    snapshot = path.parent / entry['backup']
                    self.assertTrue(snapshot.is_file())
                    if os.name != 'nt': self.assertEqual(snapshot.stat().st_mode & 0o077, 0)

    def test_overlapping_skill_destinations_are_rejected_before_writes(self):
        # Claude cannot share the Codex .agents skill file with different target metadata.
        self.run_cli('install', '--claude-home', self.home / '.agents', ok=False)
        self.assertFalse((self.home / '.aiknownofyou/runtime/configure.py').exists())

    def test_sparse_answers_compute_fallback_without_caller_evidence(self):
        self.run_cli('install')
        data = payload(100); data['answers'] = {'q' + str(i): ['skip'] for i in range(1, 9)}
        self.apply(data)
        self.assertEqual(self.state()['profile']['level'], 100)
        self.assertEqual(self.state()['profile']['selection']['reason'], 'insufficient_answers')
        data['level'] = 101
        self.apply(data, ok=False)

    def test_malformed_regions_and_foreign_skills_preflight_all_files(self):
        self.run_cli('install')
        self.apply()
        codex = self.home / '.codex/AGENTS.md'
        claude = self.home / '.claude/CLAUDE.md'
        for bad in [BEGIN, END, END + BEGIN, BEGIN + END + BEGIN + END]:
            claude.write_bytes(bad)
            before = codex.read_bytes()
            self.apply(payload(115), ok=False)
            self.assertEqual(codex.read_bytes(), before)
        skill = self.home / '.agents/skills/aiknownofyou-setup/SKILL.md'
        skill.write_text('Foreign skill')
        self.run_cli('install', ok=False)
        self.assertEqual(skill.read_text(), 'Foreign skill')

    def test_custom_homes_reapply_add_client_and_override_precedence(self):
        codex = self.base / 'Codex 日本 custom'
        claude = self.base / 'Claude custom'
        self.run_cli('install', '--target', 'codex', '--codex-home', codex)
        self.apply()
        override = codex / 'AGENTS.override.md'
        override.write_text('personal override')
        current = json.loads(self.run_cli('status').stdout)
        self.assertEqual(current['targets']['codex']['status'], '不足')
        self.assertTrue(current['needs_apply'])
        self.run_cli('apply')
        self.assertIn(BEGIN, override.read_bytes())
        self.run_cli('install', '--target', 'claude-code', '--claude-home', claude)
        self.assertIn(BEGIN, (claude / 'CLAUDE.md').read_bytes())
        self.assertEqual(self.state()['targets']['codex'], str(codex))
        self.assertTrue((self.home / '.agents/skills/aiknownofyou-setup/SKILL.md').is_file())
        self.assertFalse((codex / 'skills').exists())
        self.run_cli('install')
        self.assertFalse((self.home / '.codex').exists())

    def test_status_detects_modified_missing_and_incompatible_profile(self):
        self.run_cli('install'); self.apply()
        status = self.run_cli('status').stdout
        self.assertNotIn('105', status)
        self.assertNotIn('q1', status)
        path = self.home / '.agents/skills/aiknownofyou/references/profile.md'
        path.write_bytes(path.read_bytes().replace(b'rule_C', b'changed'))
        self.assertIn('変更', self.run_cli('status').stdout)
        path.unlink()
        self.assertIn('不足', self.run_cli('status').stdout)
        cat = self.source / 'catalog.json'
        data = fixture_catalog(); data['version'] = '2.0'; cat.write_text(json.dumps(data))
        self.assertIn('互換', self.run_cli('status').stdout)
        self.run_cli('apply', ok=False)

    def test_explicit_home_ignores_configuration_environment(self):
        env = dict(os.environ, CODEX_HOME=str(self.base / 'must-not-write-codex'),
                   CLAUDE_CONFIG_DIR=str(self.base / 'must-not-write-claude'))
        self.run_cli('install', env=env)
        self.assertEqual(self.state()['targets']['codex'], str(self.home / '.codex'))
        self.assertFalse((self.base / 'must-not-write-codex').exists())

    def test_symlink_target_is_rejected_before_other_client_changes(self):
        self.run_cli('install'); self.apply()
        path = self.home / '.claude/CLAUDE.md'
        external = self.base / 'external'; external.write_text('external')
        path.unlink(); path.symlink_to(external)
        before = (self.home / '.codex/AGENTS.md').read_bytes()
        self.apply(payload(115), ok=False)
        self.assertEqual(external.read_text(), 'external')
        self.assertEqual((self.home / '.codex/AGENTS.md').read_bytes(), before)

    def test_stdin_accepts_utf8_bom_payload(self):
        self.run_cli('install')
        self.run_cli('apply', '--input', '-', input_text='\ufeff' + json.dumps(payload()))
        self.assertTrue(json.loads(self.run_cli('status').stdout)['configured'])

    def test_powershell_prefix_quotes_apostrophes_and_uses_invocation_operator(self):
        spec = importlib.util.spec_from_file_location('configure_quoting', self.source / 'configure.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        prefix = module.command_prefix(r"C:\Python folder\python.exe", r"C:\User's 日本\configure.py",
                                       r"C:\User's 日本", windows=True)
        self.assertEqual(prefix, r"& 'C:\Python folder\python.exe' 'C:\User''s 日本\configure.py' --home 'C:\User''s 日本'".replace(' --home ', " '--home' "))

    def test_actual_catalog_and_templates_complete_installed_runtime_flow(self):
        shutil.copyfile(ROOT / 'catalog.json', self.source / 'catalog.json')
        for target in ['codex', 'claude-code']:
            shutil.copyfile(ROOT / 'templates' / target / 'SKILL.md.tmpl',
                            self.source / 'templates' / target / 'SKILL.md.tmpl')
        shutil.copyfile(ROOT / 'templates/codex/daily-SKILL.md.tmpl', self.source / 'templates/codex/daily-SKILL.md.tmpl')
        self.run_cli('install')
        guide = json.loads(self.run_cli('guide').stdout)
        self.assertEqual(len(guide['catalog']['questions']), 8)
        self.run_cli('questions')
        self.apply({'catalog_version': '0.2.0', 'answers':
                    {'q' + str(i): [choice] for i, choice in enumerate('DCBAFECE', 1)}})
        self.assertEqual(self.state()['profile']['level'], 130)
        runtime = self.home / '.aiknownofyou/runtime/configure.py'
        shutil.rmtree(self.source)
        self.run_cli('apply', script=runtime)
        self.run_cli('install', script=runtime)
        audit = json.loads(self.run_cli('explain', script=runtime).stdout)
        self.assertTrue(audit['verified'])
        self.assertEqual(audit['selection']['reason'], 'matched')
        state = json.loads(self.run_cli('status', script=runtime).stdout)
        self.assertTrue(state['configured'])
        self.assertFalse(state['needs_apply'])
        for target in state['targets'].values():
            self.assertEqual(target['status'], '整合')
            self.assertTrue(target['skill_installed'])

    def test_failed_rollback_does_not_overwrite_concurrent_external_changes(self):
        self.run_cli('install'); self.apply()
        spec = importlib.util.spec_from_file_location('configure_concurrent', self.source / 'configure.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        codex = self.home / '.agents/skills/aiknownofyou/references/profile.md'
        incoming = self.base / 'new.json'; incoming.write_text(json.dumps(payload(115)))
        real_replace = os.replace
        def failing_replace(src, dst):
            if Path(dst) == self.home / '.claude/CLAUDE.md':
                codex.write_bytes(codex.read_bytes() + b'concurrent personal edit')
                raise OSError('simulated disk failure with external edit')
            return real_replace(src, dst)
        errors = io.StringIO()
        with patch.object(module.os, 'replace', failing_replace), contextlib.redirect_stderr(errors):
            self.assertNotEqual(module.main(['--home', str(self.home), 'apply', '--input', str(incoming)]), 0)
        self.assertTrue(codex.read_bytes().endswith(b'concurrent personal edit'))
        self.assertIn('要確認', errors.getvalue())
        self.assertTrue(json.loads(self.run_cli('status').stdout)['needs_apply'])

    def test_stale_instruction_plan_preserves_intervening_personal_edit(self):
        self.run_cli('install'); self.apply()
        module = self.load_engine()
        codex = self.home / '.codex/AGENTS.md'
        claude = self.home / '.claude/CLAUDE.md'
        state_path = self.home / '.aiknownofyou/state.json'
        old_codex, old_claude, old_state = codex.read_bytes(), claude.read_bytes(), state_path.read_bytes()
        before_backups = list((self.home / '.aiknownofyou/backups').rglob('*'))
        real_commit = module.commit_changes
        def intervening_edit(*args, **kwargs):
            codex.write_bytes(old_codex + b'USER EDIT ADDED DURING APPLY')
            return real_commit(*args, **kwargs)
        incoming = self.base / 'new.json'; incoming.write_text(json.dumps(payload(115)))
        with patch.object(module, 'commit_changes', intervening_edit), contextlib.redirect_stderr(io.StringIO()):
            result = module.main(['--home', str(self.home), 'apply', '--input', str(incoming)])
        self.assertNotEqual(result, 0)
        self.assertEqual(codex.read_bytes(), old_codex + b'USER EDIT ADDED DURING APPLY')
        self.assertEqual(claude.read_bytes(), old_claude)
        self.assertEqual(state_path.read_bytes(), old_state)
        self.assertEqual(list((self.home / '.aiknownofyou/backups').rglob('*')), before_backups)

    def test_stale_skill_ownership_read_refuses_install_before_target_writes(self):
        self.run_cli('install', '--target', 'codex')
        module = self.load_engine()
        skill = self.home / '.agents/skills/aiknownofyou-setup/SKILL.md'
        state_path = self.home / '.aiknownofyou/state.json'
        old_state = state_path.read_bytes()
        real_commit = module.commit_changes
        def intervening_edit(*args, **kwargs):
            skill.write_bytes(b'Unrelated replacement after ownership check')
            return real_commit(*args, **kwargs)
        with patch.object(module, 'commit_changes', intervening_edit), contextlib.redirect_stderr(io.StringIO()):
            result = module.main(['--home', str(self.home), 'install', '--target', 'claude-code'])
        self.assertNotEqual(result, 0)
        self.assertEqual(skill.read_bytes(), b'Unrelated replacement after ownership check')
        self.assertEqual(state_path.read_bytes(), old_state)
        self.assertFalse((self.home / '.claude/skills/aiknownofyou-setup/SKILL.md').exists())

    def test_stale_saved_state_read_refuses_apply_before_instruction_writes(self):
        self.run_cli('install'); self.apply()
        module = self.load_engine()
        state_path = self.home / '.aiknownofyou/state.json'
        saved = self.state(); saved['external_note'] = 'keep edit'
        external_state = json.dumps(saved).encode('utf-8')
        before = (self.home / '.codex/AGENTS.md').read_bytes()
        real_commit = module.commit_changes
        def intervening_edit(*args, **kwargs):
            state_path.write_bytes(external_state)
            return real_commit(*args, **kwargs)
        incoming = self.base / 'new.json'; incoming.write_text(json.dumps(payload(115)))
        with patch.object(module, 'commit_changes', intervening_edit), contextlib.redirect_stderr(io.StringIO()):
            result = module.main(['--home', str(self.home), 'apply', '--input', str(incoming)])
        self.assertNotEqual(result, 0)
        self.assertEqual(state_path.read_bytes(), external_state)
        self.assertEqual((self.home / '.codex/AGENTS.md').read_bytes(), before)

    def test_changed_override_precedence_invalidates_instruction_plan(self):
        self.run_cli('install'); self.apply()
        module = self.load_engine()
        codex = self.home / '.codex/AGENTS.md'
        override = self.home / '.codex/AGENTS.override.md'
        original = codex.read_bytes()
        real_commit = module.commit_changes
        def intervening_edit(*args, **kwargs):
            override.write_bytes(b'New active personal override')
            return real_commit(*args, **kwargs)
        with patch.object(module, 'commit_changes', intervening_edit), contextlib.redirect_stderr(io.StringIO()):
            result = module.main(['--home', str(self.home), 'apply'])
        self.assertNotEqual(result, 0)
        self.assertEqual(override.read_bytes(), b'New active personal override')
        self.assertEqual(codex.read_bytes(), original)

    def test_cli_streams_are_utf8_despite_inherited_legacy_encoding(self):
        environment = dict(os.environ, PYTHONIOENCODING='cp1252')
        def invoke(*arguments, input_bytes=None, ok=True):
            result = subprocess.run([sys.executable, str(self.source / 'configure.py'),
                                     '--home', str(self.home), *arguments], capture_output=True,
                                    input=input_bytes, env=environment, cwd=self.base)
            output, error = result.stdout.decode('utf-8'), result.stderr.decode('utf-8')
            self.assertEqual(result.returncode == 0, ok, output + error)
            return output, error
        for command in ['install', 'questions', 'guide', 'status']:
            invoke(command)
        invoke('apply', '--input', '-', input_bytes=b'\xef\xbb\xbf' + json.dumps(payload()).encode('utf-8'))
        state = json.loads(invoke('status')[0])
        self.assertTrue(state['configured'])
        self.assertFalse(state['needs_apply'])
        output, error = invoke('apply', '--input', '-', input_bytes=b'{}', ok=False)
        self.assertIn('エラー', error)

    def test_executable_tolerates_embedded_streams_without_reconfigure(self):
        args = [str(self.source / 'configure.py'), '--home', str(self.home), 'questions']
        output = io.StringIO()
        with patch.object(sys, 'argv', args), patch.object(sys, 'stdin', io.StringIO()), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ended:
                runpy.run_path(str(self.source / 'configure.py'), run_name='__main__')
        self.assertEqual(ended.exception.code, 0)
        self.assertIn('q8', output.getvalue())

    def test_catalog_upgrade_installs_tooling_preserves_profile_then_reconfigures(self):
        self.run_cli('install', '--target', 'codex')
        old_profile = legacy_profile()
        saved = self.state(); saved['profile'] = old_profile
        (self.home / '.aiknownofyou/state.json').write_text(json.dumps(saved))
        codex = self.home / '.codex/AGENTS.md'
        codex.parent.mkdir(parents=True, exist_ok=True)
        old_instructions = b'personal\r\n' + BEGIN + b'\nlegacy instructions\n' + END
        codex.write_bytes(old_instructions)
        updated = fixture_catalog()
        updated['common_instructions'] = ['New catalog quality rule.']
        (self.source / 'catalog.json').write_text(json.dumps(updated), encoding='utf-8')
        output = self.run_cli('install', '--target', 'claude-code').stdout
        self.assertIn('再設定', output)
        self.assertEqual(self.state()['profile'], old_profile)
        self.assertEqual(codex.read_bytes(), old_instructions)
        self.assertFalse((self.home / '.claude/CLAUDE.md').exists())
        self.assertFalse((self.home / '.agents/skills/aiknownofyou/SKILL.md').exists())
        runtime = self.home / '.aiknownofyou/runtime/configure.py'
        self.assertEqual(json.loads((runtime.parent / 'catalog.json').read_text())['version'], '0.2.0')
        state = json.loads(self.run_cli('status', script=runtime).stdout)
        self.assertTrue(state['configured'])
        self.assertFalse(state['catalog_compatible'])
        self.assertTrue(state['needs_apply'])
        self.run_cli('apply', script=runtime, ok=False)
        audit = json.loads(self.run_cli('explain', script=runtime).stdout)
        self.assertFalse(audit['verified'])
        self.assertEqual(audit['method'], 'legacy-host-selection')
        self.assertNotIn('selection', audit)
        self.run_cli('install', script=runtime)
        self.assertEqual(self.state()['profile'], old_profile)
        self.assertEqual(codex.read_bytes(), old_instructions)
        self.apply(payload(115), script=runtime)
        self.assertNotIn(b'legacy instructions', codex.read_bytes())
        self.assertIn(b'New catalog quality rule.',
                      (self.home / '.agents/skills/aiknownofyou/references/profile.md').read_bytes())
        self.assertIn(b'New catalog quality rule.', (self.home / '.claude/CLAUDE.md').read_bytes())
        self.assertFalse(json.loads(self.run_cli('status', script=runtime).stdout)['needs_apply'])

    def test_upgrade_rejects_malformed_old_profile_without_changing_runtime(self):
        self.run_cli('install')
        state_path = self.home / '.aiknownofyou/state.json'
        state = self.state(); state['profile'] = legacy_profile(); state['profile']['level'] = True
        state_path.write_text(json.dumps(state), encoding='utf-8')
        old_runtime = (self.home / '.aiknownofyou/runtime/catalog.json').read_bytes()
        updated = fixture_catalog(); updated['common_instructions'] = ['Changed quality instructions.']
        (self.source / 'catalog.json').write_text(json.dumps(updated), encoding='utf-8')
        self.run_cli('install', ok=False)
        self.assertEqual((self.home / '.aiknownofyou/runtime/catalog.json').read_bytes(), old_runtime)

    def test_explain_checks_the_calculation_without_writing_any_home_files(self):
        self.run_cli('install', '--target', 'codex'); self.apply()
        before = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        runtime = self.home / '.aiknownofyou/runtime/configure.py'
        audit = json.loads(self.run_cli('explain', script=runtime).stdout)
        self.assertTrue(audit['verified'])
        self.assertEqual(audit['level'], 105)
        self.assertEqual(audit['selection']['reason'], 'adjacent_blend')
        self.assertEqual(audit['selection']['scores'],
                         {'80': 0, '90': 0, '100': 12, '110': 12, '120': 0, '130': 0})
        self.assertEqual(audit['selection']['support']['100'], ['q1', 'q2', 'q3', 'q4'])
        self.assertEqual({p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}, before)
        saved = self.state()['profile']
        self.run_cli('apply')
        self.assertEqual(self.state()['profile'], saved)
        self.assertNotIn('level', self.run_cli('status').stdout)

    def test_tampered_current_selection_is_not_reapplied_or_explained_as_verified(self):
        self.run_cli('install'); self.apply()
        state = self.state()
        # Bool and float substitutions must not pass Python's numeric equality.
        for value in [True, 3.0, 7]:
            with self.subTest(value=value):
                damaged = copy.deepcopy(state)
                damaged['profile']['selection']['contributions'][0]['points'] = value
                (self.home / '.aiknownofyou/state.json').write_text(json.dumps(damaged))
                before = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
                self.run_cli('apply', ok=False)
                self.run_cli('install', ok=False)
                self.run_cli('explain', ok=False)
                self.assertFalse(json.loads(self.run_cli('status').stdout)['catalog_compatible'])
                self.assertEqual({p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}, before)

    def test_malformed_saved_profile_reports_an_error_without_a_traceback(self):
        self.run_cli('install', '--target', 'codex')
        for profile in [None, [], True, 'invalid']:
            saved = self.state(); saved['profile'] = profile
            (self.home / '.aiknownofyou/state.json').write_text(json.dumps(saved))
            for command in ['apply', 'install', 'explain']:
                result = self.run_cli(command, ok=False)
                self.assertIn('エラー', result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def test_malformed_state_is_not_treated_as_a_fresh_install(self):
        state_path = self.home / '.aiknownofyou/state.json'
        state_path.parent.mkdir(parents=True)
        for state in [None, {'schema_version': True, 'targets': {}},
                      {'schema_version': 1.0, 'targets': {}}]:
            content = json.dumps(state).encode()
            state_path.write_bytes(content)
            for command in ['status', 'explain', 'install', 'apply']:
                result = self.run_cli(command, ok=False)
                self.assertIn('エラー', result.stderr)
                self.assertEqual(state_path.read_bytes(), content)
            self.assertEqual([p for p in self.home.rglob('*') if p.is_file()], [state_path])

    def test_apply_migrates_both_codex_regions_and_preserves_their_outside_bytes(self):
        self.run_cli('install', '--target', 'codex')
        directory = self.home / '.codex'; directory.mkdir(parents=True, exist_ok=True)
        for name in ['AGENTS.md', 'AGENTS.override.md']:
            (directory / name).write_bytes(b'\xef\xbb\xbfpersonal\r\n' + BEGIN + b'old full profile' + END + b'\r\nend')
        self.apply()
        for name in ['AGENTS.md', 'AGENTS.override.md']:
            content = (directory / name).read_bytes()
            self.assertTrue(content.startswith(b'\xef\xbb\xbfpersonal\r\n' + BEGIN))
            self.assertTrue(content.endswith(END + b'\r\nend'))
            self.assertNotIn(b'old full profile', content)
            self.assertNotIn(b'anchor_', content)
        (directory / 'AGENTS.override.md').unlink()
        self.assertFalse(json.loads(self.run_cli('status').stdout)['needs_apply'])

    def test_foreign_daily_skill_or_profile_prevents_all_configuration_writes(self):
        self.run_cli('install', '--target', 'codex'); self.apply()
        daily = self.home / '.agents/skills/aiknownofyou'
        for relative in ['SKILL.md', 'references/profile.md']:
            path = daily / relative
            original = path.read_bytes()
            path.write_bytes(b'Unrelated personal file')
            before = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
            self.apply(payload(115), ok=False)
            self.assertEqual({p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}, before)
            path.write_bytes(original)

    def test_renderer_keeps_the_full_integer_fade_independent_of_selected_candidates(self):
        module = self.load_engine()
        for level in range(80, 131):
            self.assertIn('Preserve quality.', module.render_instructions(level, [], fixture_catalog()))
        for level, low, high, lower_weight, upper_weight in [(83, 80, 90, 7, 3), (127, 120, 130, 3, 7)]:
            rendered = module.render_instructions(level, [], fixture_catalog())
            self.assertIn(f'重み {lower_weight}/10: anchor_{low}', rendered)
            self.assertIn(f'重み {upper_weight}/10: anchor_{high}', rendered)
        self.assertNotIn('重み', module.render_instructions(130, [], fixture_catalog()))

    def load_engine(self):
        spec = importlib.util.spec_from_file_location('configure_regression', self.source / 'configure.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_caught_write_failure_rolls_back_and_releases_lock(self):
        self.run_cli('install'); self.apply()
        spec = importlib.util.spec_from_file_location('configure_test', self.source / 'configure.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        before = {p: p.read_bytes() for p in [self.home / '.codex/AGENTS.md',
                                             self.home / '.agents/skills/aiknownofyou/references/profile.md',
                                             self.home / '.claude/CLAUDE.md',
                                             self.home / '.aiknownofyou/state.json']}
        incoming = self.base / 'new.json'; incoming.write_text(json.dumps(payload(115)))
        real_replace = os.replace
        failed = False
        def failing_replace(src, dst):
            nonlocal failed
            if Path(dst) == self.home / '.claude/CLAUDE.md' and not failed:
                failed = True
                raise OSError('simulated disk failure')
            return real_replace(src, dst)
        with patch.object(module.os, 'replace', failing_replace), contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(module.main(['--home', str(self.home), 'apply', '--input', str(incoming)]), 0)
        self.assertTrue(failed)
        for path, original in before.items(): self.assertEqual(path.read_bytes(), original)
        self.run_cli('apply')


if __name__ == '__main__':
    unittest.main()
