"""Behavioral checks for the local, reproducible initial selection rule."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
QUESTION_IDS = tuple('q' + str(i) for i in range(1, 9))
ANCHORS = (80, 90, 100, 110, 120, 130)
MAPPINGS = (
    (80, 90, 100, 110, 120, 130),
    (90, 100, 110, 120, 130, 80),
    (100, 110, 120, 130, 80, 90),
    (110, 120, 130, 80, 90, 100),
    (120, 130, 80, 90, 100, 110),
    (130, 80, 90, 100, 110, 120),
    (80, 100, 120, 90, 110, 130),
    (130, 110, 90, 120, 100, 80),
)


def fixture_catalog():
    return {
        'schema_version': 1,
        'version': '0.2.0',
        'questions': [
            {'id': qid, 'text': 'Question ' + qid,
             'choices': [
                 {'id': choice, 'text': choice, 'anchor': anchor,
                  'preference_ids': ['prefer_' + choice]}
                 for choice, anchor in zip('ABCDEF', mapping)]}
            for qid, mapping in zip(QUESTION_IDS, MAPPINGS)],
        'special_choices': [{'id': name, 'text': name}
                            for name in ('context', 'none', 'skip')],
        'selection_rules': {
            'algorithm': 'balanced-choice-v1', 'min_answered': 3,
            'min_support': 2, 'fallback_level': 100,
            'single_weight': 3, 'primary_weight': 2, 'secondary_weight': 1,
            'instructions': ['The first choice is primary.']},
        'preference_rules': {'prefer_' + choice: 'rule_' + choice
                             for choice in 'ABCDEF'},
        'level_instructions': {str(anchor): 'anchor_' + str(anchor)
                               for anchor in ANCHORS},
        'common_instructions': ['Preserve quality.'],
    }


def payload_for_anchors(*selections):
    """Encode test inputs using the fixture; expected scores stay hand-derived."""
    answers = {qid: ['skip'] for qid in QUESTION_IDS}
    for index, requested in enumerate(selections):
        anchors = requested if isinstance(requested, tuple) else (requested,)
        answers[QUESTION_IDS[index]] = [
            'ABCDEF'[MAPPINGS[index].index(anchor)] for anchor in anchors]
    return {'catalog_version': '0.2.0', 'answers': answers}


def trace_payload():
    return {'catalog_version': '0.2.0', 'answers': {
        'q1': ['A'], 'q2': ['F', 'A'], 'q3': ['E'], 'q4': ['context'],
        'q5': ['none'], 'q6': ['skip'], 'q7': ['skip'], 'q8': ['skip']}}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        source = ROOT / 'selection.py'
        self.assertTrue(source.is_file(), 'deterministic selection module is not implemented')
        spec = importlib.util.spec_from_file_location('selection_under_test', source)
        self.engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.engine)
        self.cat = fixture_catalog()

    def assert_invalid(self, function, *arguments):
        with self.assertRaises(ValueError) as raised:
            function(*arguments)
        self.assertRegex(str(raised.exception), '[\u3040-\u30ff\u4e00-\u9fff]')

    def test_each_anchor_can_win_from_eight_consistent_answers(self):
        for anchor in ANCHORS:
            with self.subTest(anchor=anchor):
                result = self.engine.select_profile(payload_for_anchors(*([anchor] * 8)), self.cat)
                self.assertEqual(result['level'], anchor)
                self.assertEqual(result['selection']['reason'], 'matched')
                self.assertEqual(result['selection']['top_candidates'], [anchor])
                self.assertEqual(result['selection']['scores'][str(anchor)], 24)
                self.assertEqual(result['selection']['support'][str(anchor)], list(QUESTION_IDS))
                self.assertEqual(sum(result['selection']['scores'].values()), 24)

    def test_each_adjacent_pair_blends_only_its_tied_maxima(self):
        for lower, upper, expected in (
                (80, 90, 85), (90, 100, 95), (100, 110, 105),
                (110, 120, 115), (120, 130, 125)):
            with self.subTest(expected=expected):
                result = self.engine.select_profile(
                    payload_for_anchors(lower, lower, lower, lower, upper, upper, upper, upper), self.cat)
                self.assertEqual(result['level'], expected)
                self.assertEqual(result['selection']['reason'], 'adjacent_blend')
                self.assertEqual(result['selection']['top_candidates'], [lower, upper])
                self.assertEqual(result['selection']['scores'][str(lower)], 12)
                self.assertEqual(result['selection']['scores'][str(upper)], 12)

    def test_primary_secondary_and_special_answers_have_a_complete_literal_trace(self):
        data = trace_payload()
        result = self.engine.select_profile(data, self.cat)
        self.assertEqual(result, {
            'catalog_version': '0.2.0', 'answers': data['answers'], 'level': 80,
            'selection': {
                'algorithm': 'balanced-choice-v1', 'reason': 'matched', 'answered_count': 3,
                'scores': {'80': 8, '90': 1, '100': 0, '110': 0, '120': 0, '130': 0},
                'support': {'80': ['q1', 'q2', 'q3'], '90': ['q2'],
                            '100': [], '110': [], '120': [], '130': []},
                'top_candidates': [80],
                'contributions': [
                    {'question': 'q1', 'choice': 'A', 'rank': 1, 'anchor': 80, 'points': 3},
                    {'question': 'q2', 'choice': 'F', 'rank': 1, 'anchor': 80, 'points': 2},
                    {'question': 'q2', 'choice': 'A', 'rank': 2, 'anchor': 90, 'points': 1},
                    {'question': 'q3', 'choice': 'E', 'rank': 1, 'anchor': 80, 'points': 3}],
                'special_answers': {'q4': 'context', 'q5': 'none', 'q6': 'skip',
                                    'q7': 'skip', 'q8': 'skip'}}})

    def test_reversing_primary_and_secondary_changes_the_winner_without_extra_weight(self):
        for primary, secondary in ((80, 90), (90, 80)):
            with self.subTest(primary=primary):
                result = self.engine.select_profile(
                    payload_for_anchors(*([(primary, secondary)] * 8)), self.cat)
                self.assertEqual(result['level'], primary)
                self.assertEqual(result['selection']['scores'][str(primary)], 16)
                self.assertEqual(result['selection']['scores'][str(secondary)], 8)
                self.assertEqual(sum(result['selection']['scores'].values()), 24)
                self.assertEqual(result['selection']['answered_count'], 8)

    def test_nonadjacent_and_three_way_ties_use_mixed_fallback(self):
        cases = [((80, 80, 80, 80, 130, 130, 130, 130), [80, 130]),
                 ((80, 80, 100, 100, 130, 130, 90, 120), [80, 100, 130])]
        for answers, candidates in cases:
            with self.subTest(candidates=candidates):
                result = self.engine.select_profile(payload_for_anchors(*answers), self.cat)
                self.assertEqual(result['level'], 100)
                self.assertEqual(result['selection']['reason'], 'mixed')
                self.assertEqual(result['selection']['top_candidates'], candidates)

    def test_fewer_than_three_ordinary_questions_take_precedence_over_support(self):
        for count in (0, 1, 2):
            with self.subTest(count=count):
                result = self.engine.select_profile(payload_for_anchors(*([80] * count)), self.cat)
                self.assertEqual(result['level'], 100)
                self.assertEqual(result['selection']['reason'], 'insufficient_answers')
                self.assertEqual(result['selection']['answered_count'], count)
                self.assertEqual(result['selection']['top_candidates'], [80] if count else [])
                self.assertEqual(result['selection']['scores']['80'], 3 * count)

    def test_any_maximum_with_one_supporting_question_requires_fallback(self):
        cases = [((80, (90, 100), (110, 120)), [80]),
                 ((80, (90, 100), (100, 90)), [80, 90, 100])]
        for answers, candidates in cases:
            with self.subTest(candidates=candidates):
                result = self.engine.select_profile(payload_for_anchors(*answers), self.cat)
                self.assertEqual(result['level'], 100)
                self.assertEqual(result['selection']['reason'], 'insufficient_support')
                self.assertEqual(result['selection']['top_candidates'], candidates)
                self.assertEqual(result['selection']['support']['80'], ['q1'])

    def test_three_supported_answers_can_select_100_without_a_fallback_reason(self):
        result = self.engine.select_profile(payload_for_anchors(100, 100, 100), self.cat)
        self.assertEqual(result['level'], 100)
        self.assertEqual(result['selection']['reason'], 'matched')
        self.assertEqual(result['selection']['scores']['100'], 9)
        self.assertEqual(result['selection']['support']['100'], ['q1', 'q2', 'q3'])

    def test_letters_use_the_mapping_of_their_own_question(self):
        data = {'catalog_version': '0.2.0', 'answers': {qid: ['A'] for qid in QUESTION_IDS}}
        result = self.engine.select_profile(data, self.cat)
        self.assertEqual(result['selection']['scores'],
                         {'80': 6, '90': 3, '100': 3, '110': 3, '120': 3, '130': 6})
        self.assertEqual([item['anchor'] for item in result['selection']['contributions']],
                         [80, 90, 100, 110, 120, 130, 80, 130])
        self.assertEqual(result['selection']['top_candidates'], [80, 130])
        self.assertEqual(result['selection']['reason'], 'mixed')

    def test_output_order_is_stable_when_input_and_catalog_dictionaries_are_reordered(self):
        data = trace_payload()
        expected = self.engine.select_profile(data, self.cat)
        data['answers'] = dict(reversed(list(data['answers'].items())))
        self.cat['questions'].reverse()
        for question in self.cat['questions']:
            question['choices'].reverse()
        actual = self.engine.select_profile(data, self.cat)
        self.assertEqual(json.dumps(actual), json.dumps(expected))

    def test_selection_does_not_mutate_or_alias_input_data(self):
        data = trace_payload()
        original_data, original_cat = copy.deepcopy(data), copy.deepcopy(self.cat)
        result = self.engine.select_profile(data, self.cat)
        self.assertEqual(data, original_data)
        self.assertEqual(self.cat, original_cat)
        result['answers']['q1'].append('B')
        self.assertEqual(data, original_data)

    def test_rejects_invalid_answer_shapes_and_missing_answers(self):
        invalid = [None, [], {}, {'catalog_version': '0.2.0', 'answers': None},
                   {'catalog_version': '0.2.0', 'answers': []}]
        for version in ('0.1.0', 'future', '', None, True, 2):
            data = trace_payload(); data['catalog_version'] = version; invalid.append(data)
        data = trace_payload(); del data['answers']['q8']; invalid.append(data)
        data = trace_payload(); data['answers']['q9'] = ['A']; invalid.append(data)
        for answer in ([], 'A', ['Z'], ['A', 'A'], ['A', 'B', 'C'], [80], [True],
                       [['A']], ['skip', 'A'], ['A', 'skip'], ['context', 'none']):
            data = trace_payload(); data['answers']['q1'] = answer; invalid.append(data)
        for data in invalid:
            with self.subTest(data=data):
                self.assert_invalid(self.engine.select_profile, data, self.cat)

    def test_external_input_cannot_supply_level_evidence_selection_or_extra_text(self):
        for key, value in (('level', 80), ('evidence', [{'question': 'q1', 'choice': 'A'}]),
                           ('selection', {}), ('instructions', 'Invented preference')):
            with self.subTest(key=key):
                data = trace_payload(); data[key] = value
                self.assert_invalid(self.engine.select_profile, data, self.cat)

    def test_valid_catalog_accepts_empty_preferences_and_optional_instructions(self):
        self.assertIsNone(self.engine.validate_catalog(self.cat))
        self.cat['preference_rules'] = {}
        for question in self.cat['questions']:
            for choice in question['choices']:
                choice['preference_ids'] = []
        del self.cat['selection_rules']['instructions']
        self.assertIsNone(self.engine.validate_catalog(self.cat))
        self.assertEqual(self.engine.select_profile(trace_payload(), self.cat)['level'], 80)

    def test_catalog_versions_must_match_but_do_not_change_algorithm_semantics(self):
        self.cat['version'] = '0.2.1'
        data = trace_payload()
        self.assert_invalid(self.engine.select_profile, data, self.cat)
        data['catalog_version'] = '0.2.1'
        result = self.engine.select_profile(data, self.cat)
        self.assertEqual(result['catalog_version'], '0.2.1')
        self.assertEqual(result['level'], 80)
        self.assertEqual(result['selection']['algorithm'], 'balanced-choice-v1')

    def test_catalog_requires_all_questions_and_unique_choices_covering_all_anchors(self):
        invalid = []
        for field, value in (('schema_version', True), ('schema_version', 1.0),
                             ('schema_version', 2), ('version', ''), ('version', None),
                             ('questions', None), ('questions', [])):
            cat = fixture_catalog(); cat[field] = value; invalid.append(cat)
        cat = fixture_catalog(); cat['questions'].pop(); invalid.append(cat)
        cat = fixture_catalog(); cat['questions'][1]['id'] = 'q1'; invalid.append(cat)
        cat = fixture_catalog(); cat['questions'][1]['id'] = 'q9'; invalid.append(cat)
        cat = fixture_catalog(); cat['questions'][0]['choices'].pop(); invalid.append(cat)
        for key, value in (('id', 'B'), ('id', 'G'), ('anchor', 90), ('anchor', True),
                           ('anchor', 80.0), ('anchor', '80'), ('anchor', 85),
                           ('anchor', [80]), ('preference_ids', None),
                           ('preference_ids', ['unknown']), ('preference_ids', [True])):
            cat = fixture_catalog(); cat['questions'][0]['choices'][0][key] = value; invalid.append(cat)
        cat = fixture_catalog(); del cat['questions'][0]['choices'][0]['anchor']; invalid.append(cat)
        cat = fixture_catalog(); cat['preference_rules']['prefer_A'] = 1; invalid.append(cat)
        for cat in [None, [], *invalid]:
            with self.subTest(cat=cat):
                self.assert_invalid(self.engine.validate_catalog, cat)

    def test_catalog_rejects_changed_or_untyped_selection_rules(self):
        for key, value in (
                ('algorithm', 'different-rule'), ('min_answered', 4), ('min_support', 1),
                ('fallback_level', 90), ('single_weight', 4), ('primary_weight', 3),
                ('secondary_weight', 0), ('min_answered', 3.0), ('secondary_weight', True),
                ('instructions', 'Not a list'), ('instructions', [1]), ('confidence', 1)):
            with self.subTest(key=key, value=value):
                cat = fixture_catalog(); cat['selection_rules'][key] = value
                self.assert_invalid(self.engine.validate_catalog, cat)
        cat = fixture_catalog(); del cat['selection_rules']['algorithm']
        self.assert_invalid(self.engine.validate_catalog, cat)

    def test_catalog_requires_distinct_supported_special_choices(self):
        for specials in ([], None, [{'id': 'skip', 'text': 'skip'}] * 3,
                         [{'id': name, 'text': name} for name in ('context', 'none', 'other')]):
            with self.subTest(specials=specials):
                cat = fixture_catalog(); cat['special_choices'] = specials
                self.assert_invalid(self.engine.validate_catalog, cat)

    def test_verification_accepts_json_roundtrip_and_reordered_object_keys(self):
        result = self.engine.select_profile(trace_payload(), self.cat)
        saved = json.loads(json.dumps(result))
        saved['selection'] = dict(reversed(list(saved['selection'].items())))
        saved = dict(reversed(list(saved.items())))
        before = copy.deepcopy(saved)
        self.assertIsNone(self.engine.verify_profile(saved, self.cat))
        self.assertEqual(saved, before)

    def test_verification_recomputes_every_selection_field_and_preserves_strict_types(self):
        original = self.engine.select_profile(trace_payload(), self.cat)
        modifications = [
            (('level',), 90), (('level',), 80.0),
            (('selection', 'algorithm'), 'different-rule'),
            (('selection', 'reason'), 'mixed'),
            (('selection', 'answered_count'), 3.0),
            (('selection', 'scores', '90'), True),
            (('selection', 'scores', '80'), 9),
            (('selection', 'support', '80'), ['q1', 'q2']),
            (('selection', 'top_candidates'), [80.0]),
            (('selection', 'contributions', 0, 'rank'), True),
            (('selection', 'contributions', 0, 'points'), 3.0),
            (('selection', 'contributions', 2, 'points'), True),
            (('selection', 'contributions', 0, 'choice'), 'B'),
            (('selection', 'special_answers', 'q4'), 'skip'),
            (('selection', 'confidence'), 1),
            (('selection', 'evidence'), []),
            (('selection', 'scores', '80'), object()),
        ]
        for path, value in modifications:
            with self.subTest(path=path, value=value):
                profile = copy.deepcopy(original)
                target = profile
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assert_invalid(self.engine.verify_profile, profile, self.cat)

    def test_verification_rejects_changed_answers_even_if_level_would_stay_the_same(self):
        profile = self.engine.select_profile(trace_payload(), self.cat)
        profile['answers']['q1'] = ['B']
        recomputed = self.engine.select_profile(
            {'catalog_version': profile['catalog_version'], 'answers': profile['answers']}, self.cat)
        self.assertEqual(profile['level'], recomputed['level'])
        self.assert_invalid(self.engine.verify_profile, profile, self.cat)

    def test_verification_rejects_wrong_top_level_contract_and_version(self):
        good = self.engine.select_profile(trace_payload(), self.cat)
        invalid = [None, [], {}]
        for key in ('catalog_version', 'answers', 'level', 'selection'):
            profile = copy.deepcopy(good); del profile[key]; invalid.append(profile)
        profile = copy.deepcopy(good); profile['evidence'] = []; invalid.append(profile)
        profile = copy.deepcopy(good); profile['catalog_version'] = '0.1.0'; invalid.append(profile)
        for profile in invalid:
            with self.subTest(profile=profile):
                self.assert_invalid(self.engine.verify_profile, profile, self.cat)


if __name__ == '__main__':
    unittest.main()
