"""Unit tests on synthetic fixture notices (no SUCSS text; layouts mimic pdftotext -layout output)."""
import sys
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import parse_notices as P  # noqa: E402
import revision_model as RM  # noqa: E402
from families import family  # noqa: E402
from acquire_notices import robots_allows  # noqa: E402
import build as B  # noqa: E402

DELETION_MEMO = """
                    STATE UNIVERSITIES CIVIL SERVICE SYSTEM
   TO:      Example Employer Representatives
   FROM:    Example Director
            Classification, Examination, and Compensation Division
   SUBJECT: Final Status: Deletion of Widget Polisher (Classification Code Number 0123)
   DATE:    March 3, 2025

A. Action: The following classification will be deleted from the Example Classification Plan,
effective Tuesday, April 1, 2025:
1. Widget Polisher (Classification Code Number 0123)
B. The Widget Inspector (Classification Code Number 0124) is currently under review and is not
affected by this notice.
"""

TABLE_CODE_ABOVE = """
   TO:            Example Employer Representatives
                                                          Digitally signed by Someone
   FROM:          Someone, Manager                        Date: 2024.08.30 11:52:37 -05'00'
                  Classification, Examination, and Compensation Division
   RE:            Final Status Notice: Gadget Management Series
   DATE:          August 30, 2024

   Consistent with our obligation, the following classification(s):

      Class Title    Action      Revised/New      Prom.    Occ. Area      Change-in-     Exam.            Effective
                                  Class Title      Line                   Title Policy   Comp.              Date

    2421                       5030               N/A         01/              1           CA           09/01/2024
    Gadget          DELETE     Gadget                     Professional
    Assistant                  Manager
    Manager
    2422            DELETE     5030 Gadget        N/A         01/              1           CA           09/01/2024
    Gadget                     Manager                    Professional
    Manager
"""

TABLE_CODE_BELOW = """
TO: Example Employer Representatives
FROM: Someone, Manager
SUBJECT: Final Status Notice - Classification Revisions
DATE: August 30, 2022

       Class Title          Action     Prom.       Occ. Area             Work Area         Change-    Exam.      Effective Date
                                        Line                                               in-Title   Comp.
Sprocket Tester             REVISE      258     01/Professional        007/Agricultural       1        CA         08/31/2022
4653                                                                      Services
Multimedia                  NEW         113     01/ Professional      210/Audio-Visual        1        CA         08/31/2022
Gizmo
Supervisor
2505
Cog Technician              REVISE      200        02/Semi-             029/Electronic        1        CA         08/31/2022
3966                                              Professional             Services
"""

RESCISSION = """
TO: Example Employer Representatives
FROM: Example Director
SUBJECT: Rescission of Proposal Notices for: Sample Nurse Series
DATE: August 28, 2026
1. Sample Nurse (Classification Code 2705)
"""

DRAFT = """
State Universities Civil Service System
Example Attendant
Draft - Class Specification Revisions
November 4, 2026
Page 1 of 2
Class Code: 0502
Effective Date: 8/31/2022
Function of Job
"""


class TestDates(unittest.TestCase):
    def test_parse_date_variants(self):
        self.assertEqual(P.parse_date('September 15th, 2023'), '2023-09-15')
        self.assertEqual(P.parse_date('Sept. 1, 2010'), '2010-09-01')
        self.assertEqual(P.parse_date('05/19/2026'), '2026-05-19')
        self.assertEqual(P.parse_date('7/1/13'), '2013-07-01')
        self.assertIsNone(P.parse_date('no date here'))
        self.assertIsNone(P.parse_date('February 30, 2020'))


class TestNoticeParsing(unittest.TestCase):
    def test_deletion_memo(self):
        d = P.parse_document(DELETION_MEMO)
        self.assertEqual(d['kind'], 'notice')
        self.assertEqual(d['stage'], 'final')
        self.assertEqual(d['doc_date'], '2025-03-03')
        self.assertEqual(d['primary_action'], 'abolish')
        self.assertIn('2025-04-01', d['effective_dates'])
        roles = {m['class_code']: m['role'] for m in d['mentions']}
        self.assertEqual(roles['0123'], 'affected')
        self.assertEqual(roles['0124'], 'context')     # "not affected by this notice"
        hints = {m['class_code']: m['title_hint'] for m in d['mentions'] if m['class_code'] == '0123'}
        self.assertEqual(hints['0123'], 'Widget Polisher')
        # the FROM line's "Compensation Division" must not create a pay note
        self.assertNotIn('pay_note', d['flags'])

    def test_table_code_above_with_successor_and_signature_date(self):
        d = P.parse_document(TABLE_CODE_ABOVE)
        self.assertEqual(d['doc_date'], '2024-08-30')
        self.assertEqual(d['date_source'], 'memo_date')     # not the digital-signature line
        rows = {m['class_code']: m for m in d['mentions'] if m['context'] == 'table_row'}
        self.assertEqual(set(rows), {'2421', '2422'})
        self.assertEqual(rows['2421']['action'], 'abolish')
        self.assertEqual(rows['2421']['target_codes'], ['5030'])
        self.assertEqual(rows['2422']['target_codes'], ['5030'])
        self.assertEqual(rows['2421']['title_hint'], 'Gadget Assistant Manager')
        tgt = [m for m in d['mentions'] if m['class_code'] == '5030']
        self.assertEqual(tgt[0]['role'], 'target')
        self.assertEqual(tgt[0]['action'], 'successor_or_target')

    def test_table_code_below_mixed_actions(self):
        d = P.parse_document(TABLE_CODE_BELOW)
        rows = {m['class_code']: m['action'] for m in d['mentions'] if m['context'] == 'table_row'}
        self.assertEqual(rows, {'4653': 'revise_spec', '2505': 'new_class', '3966': 'revise_spec'})
        titles = {m['class_code']: m['title_hint'] for m in d['mentions']}
        self.assertEqual(titles['2505'], 'Multimedia Gizmo Supervisor')
        self.assertEqual(d['primary_action'], 'new_class')

    def test_rescission(self):
        d = P.parse_document(RESCISSION)
        self.assertEqual(d['stage'], 'rescission')
        self.assertEqual([m['action'] for m in d['mentions']], ['rescind'])

    def test_draft_attachment(self):
        d = P.parse_document(DRAFT)
        self.assertEqual(d['kind'], 'draft_attachment')
        self.assertEqual(d['stage'], 'draft')
        self.assertEqual(d['doc_date'], '2026-11-04')
        self.assertEqual({m['class_code'] for m in d['mentions']}, {'0502'})

    def test_title_hint_cannot_carry_prose(self):
        self.assertEqual(P.sanitize_title('Physical Therapist IV Change-In-Title Polic are recommended with p'), 'Physical Therapist IV')
        self.assertEqual(P.sanitize_title('Director of Nursing Voiding/Deleting Registers The registers for'), 'Director of Nursing')
        self.assertEqual(P.sanitize_title('Widget Polisher shall be voided at the close'), 'Widget Polisher')
        self.assertIsNone(P.sanitize_title('the registers'))

    def test_no_false_codes_from_phone_or_address(self):
        txt = 'OFFICE 217/278-3150 FAX 217/278-3159\n1717 Philo Road, Suite 24\nUrbana 61802-6099\n'
        self.assertEqual(P.find_mentions(txt), [])


class TestHelpers(unittest.TestCase):
    def test_robots(self):
        robots = 'User-agent: *\nDisallow: /csn.aspx\nDisallow: /csn_detail.aspx\n'
        self.assertFalse(robots_allows(robots, '/csn.aspx'))
        self.assertTrue(robots_allows(robots, '/documents/csn/3321.pdf'))

    def test_family(self):
        self.assertEqual(family('Information Technology Technical Associate', '01 Professional'), 'IT, data & security')
        self.assertEqual(family('Office Support Specialist', '04 Clerical'), 'Clerical & office support')
        self.assertEqual(family('Police Officer', '13 Protective Services'), 'Protective services')
        self.assertEqual(family('Plumber', '14 Skilled Trades'), 'Skilled trades')

    def test_title_pattern(self):
        self.assertEqual(B.title_pattern('Driver', 'Heavy Driver', '1236', '1236', 'revise_spec'), 'title_change_in_place')
        self.assertEqual(B.title_pattern('Systems Programmer I', 'IT Technical Associate', '3150', '5031', 'abolish'),
                         'merged_into_other_class')
        self.assertEqual(B.title_pattern('Clerk I', 'Clerk 1', '0001', '0002', 'revise_spec'), 'level_renumbered')
        self.assertEqual(B.title_pattern('Driver Helper', 'Driver', '0001', '0002', 'revise_spec'), 'retitled_shared_words')

    def test_spearman(self):
        self.assertEqual(B.spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])['rho'], -1.0)


def _tl(code, **kw):
    base = {'class_code': code, 'class_title': 'X', 'job_family': 'Other', 'occupational_line': '01 Professional',
            'in_catalog': True, 'on_series_page': True, 'series_id': 1, 'status': 'active', 'created_date': None,
            'abolished_date': None, 'spec_effective_date': None, 'series_last_action': 'Revised',
            'hot_tech_share': None, 'emerging_task_rate': None, 'aei_observed_exposure': None, 'aei_task_coverage': None}
    base.update(kw)
    return base


class TestModel(unittest.TestCase):
    def test_metrics(self):
        self.assertEqual(RM.auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]), 1.0)
        self.assertEqual(RM.auc([0, 1], [0.5, 0.5]), 0.5)
        self.assertEqual(RM.avg_precision([1, 0, 1], [0.9, 0.8, 0.7]), round((1 + 2 / 3) / 2, 4))
        self.assertEqual(RM.prec_at([1, 0, 0, 1], [4, 3, 2, 1], 2), 0.5)

    def test_no_series_date_leakage_and_labels(self):
        tl = [_tl('0001', spec_effective_date='2010-01-01'), _tl('0002', spec_effective_date='2021-03-01')]
        ev = {'0001': [{'source': 'csn', 'role': 'affected', 'event_date': '2008-05-01', 'effective_date': '2008-07-01',
                        'stage': 'final', 'action': 'revise_spec', 'csn': 1}],
              '0002': [{'source': 'series_page', 'role': 'affected', 'event_date': '2021-03-01', 'effective_date': '2021-03-01',
                        'stage': 'in_force', 'action': 'revise_spec', 'context': 'spec_effective_date', 'csn': None}]}
        T = date(2019, 7, 1)
        rows = {r['class_code']: r for r in RM.features_at(T, tl, ev, {1: {'0001', '0002'}}, date(2004, 1, 1))}
        self.assertEqual(rows['0001']['age_censored'], 0)
        self.assertAlmostEqual(rows['0001']['age_years'], 11.0, places=0)
        # class 0001's series date (2010, before T) must NOT be used as history in the backtest
        self.assertGreater(rows['0001']['age_years'], 10.5)
        self.assertEqual(rows['0002']['age_censored'], 1)
        lab = RM.label_at(T, ['0001', '0002'], ev, None)
        self.assertEqual(lab, {'0001': 0, '0002': 1})

    def test_created_after_cutoff_excluded(self):
        tl = [_tl('0003', series_last_action='Add', spec_effective_date='2024-01-01')]
        self.assertEqual(RM.features_at(date(2019, 7, 1), tl, {}, {}, date(2004, 1, 1)), [])


if __name__ == '__main__':
    unittest.main()
