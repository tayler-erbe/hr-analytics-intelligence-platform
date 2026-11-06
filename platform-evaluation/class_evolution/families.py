"""Transparent job-family rules for SUCSS class titles (first match wins).

These are keyword rules on the lower-cased class title, with the SUCSS occupational line as a
fallback. They are deliberately simple and auditable; they are not an official SUCSS taxonomy.
"""
import re

FAMILIES = [
    ('IT, data & security', r'information technology|\bit\b|computer|network|programmer|systems? (analyst|administrator|specialist|programmer)|software|\bweb\b|\bdata\b|database|cyber|information security|applications? (analyst|programmer|developer)|microcomputer|\blan\b|telecommunication|electronic (data|records)'),
    ('Library, museum & archives', r'librar|archiv|museum|curator|conservator'),
    ('Health & medical', r'nurse|nursing|social work|medical|clinic|pharm|radiolog|sonograph|therap|patholog|phlebot|dental|physician|health|surgical|respiratory|cardio|histolog|dietitian|psycholog|optometr|veterinar|laboratory animal|electroencephalograph|tumor|pulmonary|perfusion|mammograph|ultrasound|anesthe'),
    ('Protective services', r'police|security|public safety|fire|telecommunicator|guard|emergency|parking enforcement|compliance examiner'),
    ('Human resources', r'human resource|personnel|employment|benefit|compensation|labor relations|training'),
    ('Finance & procurement', r'account|budget|fiscal|financ|purchas|procure|grant|bursar|cashier|payroll|buyer|audit|collection|loan|revenue|treasur|insurance|contract (administrator|specialist)'),
    ('Student & academic services', r'student|admission|(?<!tumor )registrar|academic|advis|counsel|career|residence|housing|scholarship|financial aid|instructional|child development|interpreter|testing|tutor'),
    ('Communications, media & arts', r'media|communication|broadcast|photograph|graphic|artist|editor|publication|writer|journal|printing|press|audio|visual|television|radio|music|theat|stage|marketing|public (information|relations)|cartograph|illustrat|digital imaging|pre-press|prepress'),
    ('Science & research support', r'research|scien|laborator|chemist|biolog|physic|technician|technologist|meteorolog|archaeolog|herbari|greenhouse|electron microscop|instrument'),
    ('Skilled trades', r'electrician|plumb|carpent|mechanic|painter|locksmith|steam|pipefitter|mason|roofer|refrigeration|operating engineer|sheet metal|plasterer|tinsmith|elevator|boiler|machinist|welder|insulator|glazier|millwright|cabinet|upholster|sign hanger|trades|foreman|sub-foreman|power plant|stationary engineer|lineman|ironworker'),
    ('Facilities, grounds & custodial', r'building|maintenance|custod|grounds|facilit|housekeep|janitor|laborer|garden|horticult|greens|forest|landscap|pest|labor\b|attendant|service worker|park'),
    ('Transportation & stores', r'driver|transport|automotive|aircraft|aviation|pilot|flight|bus\b|vehicle|stores|storekeeper|warehouse|shipping|receiving|mail|parts|inventory|material'),
    ('Food & domestic services', r'food|cook|baker|dining|kitchen|chef|meat|catering|laundry|domestic'),
    ('Agriculture & animal care', r'agricult|farm|animal|livestock|crop|dairy|swine|poultry|equine|herdsman|seed|plant (breeder|science)|veterin'),
    ('Clerical & office support', r'clerk|clerical|secretar|office (support|assistant|manager|specialist|administrator)|typist|receptionist|stenograph|word processing|data entry|records|document|switchboard|telephone operator|chief clerk|keyboard|account technician|staff (clerk|secretary)'),
    ('Management & administration', r'director|manager|administrator|administrative|coordinator|supervisor|superintendent|chief|executive|officer|program|business|specialist|associate|assistant|representative|analyst'),
]
_COMPILED = [(n, re.compile(rx)) for n, rx in FAMILIES]
OCC_LINE_FALLBACK = {
    '04': 'Clerical & office support', '05': 'Transportation & stores', '06': 'Transportation & stores',
    '07': 'Agriculture & animal care', '08': 'Facilities, grounds & custodial',
    '09': 'Food & domestic services', '10': 'Food & domestic services', '11': 'Skilled trades',
    '12': 'Health & medical', '13': 'Protective services', '14': 'Skilled trades',
    '15': 'Facilities, grounds & custodial', '16': 'Facilities, grounds & custodial',
}
FAMILY_NAMES = [n for n, _ in FAMILIES] + ['Other']


def family(title, occupational_line=None):
    t = (title or '').lower()
    occ = (occupational_line or '')[:2]
    # occupational lines that are unambiguous override generic title words
    if occ == '04' and not re.search(r'information technology|computer|\bdata\b|account', t):
        return 'Clerical & office support'
    if occ in ('12',) and not re.search(r'clerk|secretar', t):
        return 'Health & medical'
    if occ == '13':
        return 'Protective services'
    for name, rx in _COMPILED:
        if rx.search(t):
            return name
    return OCC_LINE_FALLBACK.get(occ, 'Other')


OCC_LINES = {
    '01': 'Professional', '02': 'Semi-Professional', '03': 'Managerial', '04': 'Clerical',
    '05': 'Stores', '06': 'Aeronautical', '07': 'Agricultural', '08': 'Custodial Services',
    '09': 'Domestic Services', '10': 'Food Services', '11': 'Power, Heat, and Light Services',
    '12': 'Medical Services', '13': 'Protective Services', '14': 'Skilled Trades',
    '15': 'Semi-Skilled Trades', '16': 'Unskilled Trades',
}
