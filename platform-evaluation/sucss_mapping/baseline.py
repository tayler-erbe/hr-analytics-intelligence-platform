"""Replication of the old title-only lexical baseline (scripts/prepare_pilot.py, title_lexical_baseline_v1),
extended from top-3 to top-5 so top-5 accuracy can be compared. The similarity function is copied verbatim
so this module does not import or modify files outside sucss_mapping/."""
import re
from difflib import SequenceMatcher

METHOD = 'title_lexical_baseline_v1'


def normalized(text):
    return re.sub(r'[^a-z0-9 ]', ' ', text.lower()).split()


def similarity(left, right):
    a, b = set(normalized(left)), set(normalized(right))
    overlap = len(a & b) / len(a | b) if a | b else 0
    sequence = SequenceMatcher(None, ' '.join(sorted(a)), ' '.join(sorted(b))).ratio()
    return round(0.7 * overlap + 0.3 * sequence, 4)


def rank(title, occupations, k=5):
    # Python's sort is stable; prepare_pilot sorts the occupation list in source order, so we keep that order.
    scored = [(similarity(title, o['title']), i, o) for i, o in enumerate(occupations)]
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [{'rank': r, 'onetsoc_code': o['onetsoc_code'], 'occupation_title': o['title'], 'title_similarity': s}
            for r, (s, _, o) in enumerate(scored[:k], 1)]
