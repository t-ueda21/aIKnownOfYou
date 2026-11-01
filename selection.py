"""Pure, deterministic initial selection; no files, network, or model calls."""
import json


QUESTION_IDS = tuple('q' + str(i) for i in range(1, 9))
ANCHORS = (80, 90, 100, 110, 120, 130)
CHOICE_IDS = frozenset('ABCDEF')
SPECIAL_IDS = frozenset(('context', 'none', 'skip'))
RULES = {
    'algorithm': 'balanced-choice-v1',
    'min_answered': 3,
    'min_support': 2,
    'fallback_level': 100,
    'single_weight': 3,
    'primary_weight': 2,
    'secondary_weight': 1,
}


def validate_catalog(cat):
    """Reject unsupported rule semantics and ambiguous choice mappings."""
    if (not isinstance(cat, dict) or type(cat.get('schema_version')) is not int
            or cat['schema_version'] != 1 or not isinstance(cat.get('version'), str)
            or not cat['version'].strip()):
        raise ValueError('カタログの形式またはバージョンが不正です。')
    rules = cat.get('selection_rules')
    if (not isinstance(rules, dict)
            or set(rules) not in (set(RULES), set(RULES) | {'instructions'})
            or any(type(rules.get(key)) is not type(value) or rules[key] != value
                   for key, value in RULES.items())):
        raise ValueError('カタログの選定規則に互換性がありません。')
    if 'instructions' in rules and (not isinstance(rules['instructions'], list)
                                   or any(not isinstance(text, str) for text in rules['instructions'])):
        raise ValueError('カタログの選定規則の説明が不正です。')
    preferences = cat.get('preference_rules')
    if (not isinstance(preferences, dict)
            or any(not isinstance(key, str) or not key or not isinstance(value, str)
                   for key, value in preferences.items())):
        raise ValueError('カタログの補助指示が不正です。')
    questions = cat.get('questions')
    if not isinstance(questions, list) or len(questions) != len(QUESTION_IDS):
        raise ValueError('カタログには固定の8問が必要です。')
    seen_questions = set()
    for question in questions:
        if (not isinstance(question, dict) or not isinstance(question.get('id'), str)
                or question['id'] not in QUESTION_IDS or question['id'] in seen_questions):
            raise ValueError('カタログの設問IDが不正または重複しています。')
        seen_questions.add(question['id'])
        choices = question.get('choices')
        if not isinstance(choices, list) or len(choices) != len(ANCHORS):
            raise ValueError('各設問には6つの通常の選択肢が必要です。')
        seen_choices, seen_anchors = set(), set()
        for choice in choices:
            if (not isinstance(choice, dict) or not isinstance(choice.get('id'), str)
                    or choice['id'] not in CHOICE_IDS or choice['id'] in seen_choices
                    or type(choice.get('anchor')) is not int or choice['anchor'] not in ANCHORS
                    or choice['anchor'] in seen_anchors):
                raise ValueError('選択肢はA〜Fと6つの構成を一つずつ対応させてください。')
            seen_choices.add(choice['id'])
            seen_anchors.add(choice['anchor'])
            ids = choice.get('preference_ids')
            if (not isinstance(ids, list)
                    or any(not isinstance(pid, str) or pid not in preferences for pid in ids)
                    or len(ids) != len(set(ids))):
                raise ValueError('選択肢に対応する補助指示が不正です。')
    special = cat.get('special_choices')
    if (not isinstance(special, list) or len(special) != len(SPECIAL_IDS)
            or any(not isinstance(choice, dict) or not isinstance(choice.get('id'), str)
                   for choice in special)
            or {choice['id'] for choice in special} != SPECIAL_IDS):
        raise ValueError('カタログの特別な選択肢が不正です。')


def _validated_answers(payload, cat):
    if not isinstance(payload, dict) or set(payload) != {'catalog_version', 'answers'}:
        raise ValueError('入力にはcatalog_versionとanswersだけを指定してください。')
    if (not isinstance(payload['catalog_version'], str)
            or payload['catalog_version'] != cat['version']):
        raise ValueError('回答とカタログのバージョンに互換性がありません。')
    answers = payload['answers']
    if not isinstance(answers, dict) or set(answers) != set(QUESTION_IDS):
        raise ValueError('全8問の回答が必要です。')
    validated = {}
    for qid in QUESTION_IDS:
        selected = answers[qid]
        if (not isinstance(selected, list) or not 1 <= len(selected) <= 2
                or any(not isinstance(choice, str) for choice in selected)
                or len(set(selected)) != len(selected)):
            raise ValueError('回答の形式が不正です: ' + qid)
        if selected[0] in SPECIAL_IDS:
            if len(selected) != 1:
                raise ValueError('特別な回答は単独で指定してください: ' + qid)
        elif any(choice not in CHOICE_IDS for choice in selected):
            raise ValueError('未知の選択肢です: ' + qid)
        validated[qid] = list(selected)
    return validated


def select_profile(payload, cat):
    """Compute the complete stored profile from an exact answers-only payload."""
    validate_catalog(cat)
    answers = _validated_answers(payload, cat)
    questions = {question['id']: question for question in cat['questions']}
    scores = {str(anchor): 0 for anchor in ANCHORS}
    support = {str(anchor): set() for anchor in ANCHORS}
    contributions, special_answers = [], {}
    answered = 0
    rules = cat['selection_rules']
    for qid in QUESTION_IDS:
        selected = answers[qid]
        if selected[0] in SPECIAL_IDS:
            special_answers[qid] = selected[0]
            continue
        answered += 1
        choices = {choice['id']: choice for choice in questions[qid]['choices']}
        weights = ((rules['single_weight'],) if len(selected) == 1 else
                   (rules['primary_weight'], rules['secondary_weight']))
        for rank, (choice, points) in enumerate(zip(selected, weights), 1):
            anchor = choices[choice]['anchor']
            scores[str(anchor)] += points
            support[str(anchor)].add(qid)
            contributions.append({'question': qid, 'choice': choice, 'rank': rank,
                                  'anchor': anchor, 'points': points})
    maximum = max(scores.values())
    top = [anchor for anchor in ANCHORS if maximum > 0 and scores[str(anchor)] == maximum]
    level = rules['fallback_level']
    if answered < rules['min_answered']:
        reason = 'insufficient_answers'
    elif not top or any(len(support[str(anchor)]) < rules['min_support'] for anchor in top):
        reason = 'insufficient_support'
    elif len(top) == 1:
        level, reason = top[0], 'matched'
    elif len(top) == 2 and top[1] - top[0] == 10:
        level, reason = (top[0] + top[1]) // 2, 'adjacent_blend'
    else:
        reason = 'mixed'
    selection = {
        'algorithm': rules['algorithm'],
        'reason': reason,
        'answered_count': answered,
        'scores': scores,
        'support': {str(anchor): [qid for qid in QUESTION_IDS if qid in support[str(anchor)]]
                    for anchor in ANCHORS},
        'top_candidates': top,
        'contributions': contributions,
        'special_answers': special_answers,
    }
    return {'catalog_version': cat['version'], 'answers': answers,
            'level': level, 'selection': selection}


def verify_profile(profile, cat):
    """Recompute without mutation; reject extra data and noncanonical JSON types."""
    if (not isinstance(profile, dict)
            or set(profile) != {'catalog_version', 'answers', 'level', 'selection'}):
        raise ValueError('保存プロフィールの形式が不正です。')
    expected = select_profile({'catalog_version': profile['catalog_version'],
                               'answers': profile['answers']}, cat)
    try:
        actual_json = json.dumps(profile, ensure_ascii=False, sort_keys=True, allow_nan=False)
        expected_json = json.dumps(expected, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError('保存された選定結果の形式が不正です。') from None
    if actual_json != expected_json:
        raise ValueError('保存された選定結果が回答からの再計算と一致しません。')
