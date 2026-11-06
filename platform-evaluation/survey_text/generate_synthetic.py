"""Seeded generator of SYNTHETIC Qualtrics-like survey exports.

EVERYTHING THIS SCRIPT WRITES IS SYNTHETIC. No real responses, people, units,
names, e-mail addresses, phone numbers or UINs are used. Unit names are
generic fictional labels. Names are fictional combinations; e-mails use the
reserved example.edu domain; phone numbers use the reserved 555-01xx block.

Outputs (survey_text/data/synthetic/):
  ws_export.csv            Workplace Satisfaction export (~3,000 rows), Qualtrics 3-header layout
  exit_export.csv          Exit survey export (~800 rows), Qualtrics 3-header layout
  unit_headcount.csv       synthetic headcount and separations by unit and fiscal year
  roster_names.csv         synthetic staff directory (used by the roster redaction layer)
  decoy_manifest.json      ground truth: every PII-like decoy inserted, by ResponseId
  theme_truth.csv          ground truth themes inserted per response (generator knowledge)
  gold/gold_sample.csv     SIMULATED double-coded gold sample (truth + simulated coder noise)

Run:  python survey_text/generate_synthetic.py [--seed 20261106]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "synthetic"
DEFAULT_SEED = 20261106

UNITS = [  # (name, weight, eNPS effect, headcount)
    ("Applied Sciences College", 14, 0.3, 1450),
    ("Arts & Humanities College", 9, 0.1, 820),
    ("Health Sciences College", 10, -0.4, 1010),
    ("Business School", 6, 0.6, 520),
    ("Research Administration", 6, -0.6, 410),
    ("Facilities & Services", 13, -0.9, 1280),
    ("Technology Services", 10, 0.2, 760),
    ("Student Affairs", 9, -0.2, 830),
    ("University Libraries", 6, 0.4, 470),
    ("Human Resources Office", 4, 0.0, 260),
    ("Athletics Operations", 4, -0.3, 300),
    ("Field Research Station", 0.25, 0.0, 28),  # deliberately tiny: exercises suppression
]
ROLE_FAMILIES = [  # (name, weight, effect)
    ("Faculty", 18, 0.2),
    ("Academic Professional", 26, 0.1),
    ("Civil Service - Admin/Clerical", 22, -0.4),
    ("Civil Service - Technical", 14, -0.1),
    ("Civil Service - Trades/Building", 12, -0.6),
    ("Postdoc/Research Staff", 8, 0.0),
]
TENURE = ["<1 yr", "1-3 yrs", "3-5 yrs", "5-10 yrs", "10-20 yrs", "20+ yrs"]
TENURE_W = [10, 22, 18, 22, 18, 10]
EXIT_TENURE_W = [16, 26, 16, 14, 10, 18]

THEMES = ["workload", "pay", "career_growth", "manager_support", "remote_hybrid", "recognition",
          "bureaucracy", "ai_tools", "culture_belonging", "relocation_retirement"]

# eNPS effect of a theme mention, by valence
EFFECT = {
    "workload": (-2.4, 0.6), "pay": (-1.6, 0.5), "career_growth": (-1.5, 0.7),
    "manager_support": (-2.2, 1.6), "remote_hybrid": (-1.3, 1.1), "recognition": (-1.7, 1.0),
    "bureaucracy": (-1.1, 0.2), "ai_tools": (-0.4, 0.4), "culture_belonging": (-2.0, 1.4),
    "relocation_retirement": (-0.2, 0.2),
}
BASE_RATE = {  # probability a WS comment mentions the theme
    "workload": 0.30, "pay": 0.26, "career_growth": 0.20, "manager_support": 0.18,
    "remote_hybrid": 0.15, "recognition": 0.14, "bureaucracy": 0.17, "ai_tools": 0.10,
    "culture_belonging": 0.15, "relocation_retirement": 0.03,
}
P_NEG = {  # probability a mention is negative
    "workload": 0.85, "pay": 0.8, "career_growth": 0.75, "manager_support": 0.5, "remote_hybrid": 0.4,
    "recognition": 0.65, "bureaucracy": 0.9, "ai_tools": 0.45, "culture_belonging": 0.5,
    "relocation_retirement": 0.5,
}

# Templates. Kinds: neg / pos / implicit (deliberately avoids codebook lexicon terms,
# so the baseline coder SHOULD miss some; measured honestly in evaluation).
T = {
    "workload": {
        "neg": ["We have been short-staffed {dur} and the workload is not sustainable.",
                "Two positions in our office have been unfilled {dur}, so a few of us are covering for them.",
                "I am burned out. Evenings and weekends are now expected.",
                "There is simply too much work on my plate and no relief in sight.",
                "Staffing has not recovered since the reorganization; everyone is stretched thin.",
                "The pace during {season} is exhausting and nobody plans for it.",
                "I regularly work overtime just to keep up with basic requests."],
        "pos": ["My workload is manageable and my team shares the load fairly.",
                "Staffing finally improved this year, which made a real difference."],
        "implicit": ["I cannot remember the last time I took a lunch break.",
                     "Three people used to do what I now do alone."],
    },
    "pay": {
        "neg": ["My salary has not kept up with inflation {dur}.",
                "The raise pool was tiny again; I could make far more at a private employer.",
                "Salary compression means new hires earn almost what I do after {years} years.",
                "Pay for {role_short} roles is well below the market rate.",
                "Cost of living keeps going up but our wages do not.",
                "I am underpaid compared to peers at other universities."],
        "pos": ["The benefits package is the main reason I stay.",
                "Pay is fair for what I do, and the merit increase helped."],
        "implicit": ["I took a second job on weekends to cover rent.",
                     "A grocery store manager in town earns more than I do."],
    },
    "career_growth": {
        "neg": ["There is no clear path to promotion for people in my role.",
                "My reclassification request has been pending {dur}.",
                "This feels like a dead-end job; the only way up is out.",
                "I would like professional development funding but there is none.",
                "I have been stuck in the same title for {years} years with no advancement.",
                "Career growth is not discussed unless you threaten to leave."],
        "pos": ["I have been encouraged to grow and was promoted last year.",
                "The mentoring program helped me plan my next step."],
        "implicit": ["I have hit the ceiling here and nobody seems to care.",
                     "Every internal opening goes to someone from outside."],
    },
    "manager_support": {
        "neg": ["My supervisor rarely gives feedback and cancels our one-on-ones.",
                "Our director micromanages every decision.",
                "My manager takes credit for the team's work and does not support us.",
                "I do not trust my supervisor to treat people fairly.",
                "New supervisors get no training in how to manage people."],
        "pos": ["My supervisor has my back and is the reason I stay.",
                "My manager gives honest feedback and supports flexible scheduling.",
                "I have a great boss who checks in regularly.",
                "Our team lead is fair, clear and approachable."],
        "implicit": ["The person I report to has not asked how I am doing in a year.",
                     "The person I report to is the best part of this job."],
    },
    "remote_hybrid": {
        "neg": ["The return-to-office push ignored that our work can be done remotely.",
                "Hybrid rules differ by unit and feel arbitrary.",
                "My commute is ninety minutes and telework requests were denied.",
                "Being required in the office five days lost us two good people."],
        "pos": ["My hybrid schedule makes this job workable with young kids.",
                "Being able to work from home two days a week is worth more than a raise to me.",
                "The flexibility to adjust my hours is excellent."],
        "implicit": ["Being forced to sit in a cubicle to answer email makes no sense.",
                     "Two days at the kitchen table each week changed my life."],
    },
    "recognition": {
        "neg": ["Nobody notices the extra effort until something goes wrong.",
                "I feel invisible; good work goes unrecognized.",
                "Staff are taken for granted compared to faculty.",
                "There is no acknowledgment when we cover gaps for months."],
        "pos": ["I feel valued and appreciated by my unit.",
                "Our unit's staff award was a nice touch and people noticed."],
        "implicit": ["A simple word of thanks from leadership would go a long way.",
                     "It would be nice if someone said our name at the all-staff meeting."],
    },
    "bureaucracy": {
        "neg": ["A simple purchase takes six signatures and three weeks.",
                "The hiring process takes so long that candidates accept other offers.",
                "Too much paperwork and too many approvals for routine tasks.",
                "Policies change without notice and nobody can explain the process.",
                "We spend more time on forms and tickets than on actual work.",
                "Red tape between offices makes every project slower."],
        "pos": ["The new online approval process saved us a lot of time."],
        "implicit": ["Getting anything done here means chasing the same email chain for a month.",
                     "Nothing moves until it has been reviewed by four offices."],
    },
    "ai_tools": {
        "neg": ["We were told to use AI tools but nobody has trained us.",
                "There is no clear guidance on which AI tools are allowed for sensitive data.",
                "I worry that automation will be used to cut positions instead of workload.",
                "The Copilot rollout was confusing and the training was too basic."],
        "pos": ["Copilot saves me about an hour a day on drafting.",
                "The AI training series was practical and I now use it weekly.",
                "Illinois-style chat tools help me summarize long policy documents."],
        "implicit": ["I would love a workshop on the new writing assistant everyone mentions.",
                     "The new drafting assistant cut my report time in half."],
    },
    "culture_belonging": {
        "neg": ["The culture in our unit is toxic and there are cliques.",
                "Morale is the lowest I have seen in {years} years.",
                "I do not feel respected or included in decisions.",
                "Leadership talks about inclusion but staff voices are excluded."],
        "pos": ["My colleagues are wonderful and I feel like I belong here.",
                "There is a real sense of community and mission in our office.",
                "People here are respectful and welcoming."],
        "implicit": ["People eat lunch together and help each other without being asked.",
                     "I dread walking into the building most mornings."],
    },
    "relocation_retirement": {
        "neg": ["I am retiring after {years} years and nobody has asked about knowledge transfer.",
                "My spouse took a job out of state so we are relocating.",
                "I am moving closer to family to help care for a parent.",
                "I reached pension eligibility under SURS and decided to retire."],
        "pos": ["Retiring with good memories; this was a good place to work.",
                "Relocating for family reasons, not because of the job."],
        "implicit": ["After {years} years it is simply time to stop working and enjoy life.",
                     "We bought a house near the grandchildren three states away."],
    },
}
FILLERS = ["Overall it is an okay place to work.", "Not much else to add.", "I hope this survey leads to change.",
           "Thanks for asking.", "Some things are good, some are not.", "Hard to summarize in a box."]
SLOTS = {
    "dur": ["for over a year", "for eight months", "since last spring", "for two budget cycles", "for most of this year"],
    "season": ["the start of the semester", "fiscal year end", "move-in week", "grant deadlines"],
    "years": ["6", "9", "12", "15", "22", "28"],
    "role_short": ["IT", "lab", "clerical", "trades", "advising"],
}

FIRST = ["Avery", "Brennan", "Calla", "Dorian", "Elsbeth", "Fenwick", "Gianna", "Harlow", "Isidore", "Jolene",
         "Kestrel", "Lucian", "Marisol", "Nolan", "Odessa", "Perrin", "Quilla", "Rosalind", "Soren", "Tamsin",
         "Ulric", "Verity", "Wendell", "Xiomara", "Yorick", "Zelda", "Ambrose", "Bettina", "Caspian", "Delphine"]
LAST = ["Abernathy", "Brightwater", "Castellane", "Dunmore", "Everhart", "Fairbanks", "Galloway", "Hollister",
        "Ingersoll", "Jasperson", "Kittredge", "Lockhart", "Merriweather", "Northcott", "Oakhurst", "Pemberton",
        "Quackenbush", "Redfield", "Stanhope", "Thistlewood", "Underhill", "Vandermeer", "Whitlock", "Yardley"]
EXIT_REASONS = [
    ("Better pay elsewhere", "pay"), ("Career advancement elsewhere", "career_growth"),
    ("Workload / burnout", "workload"), ("Supervisor relationship", "manager_support"),
    ("Remote or flexible work elsewhere", "remote_hybrid"), ("Retirement", "relocation_retirement"),
    ("Relocation / family", "relocation_retirement"), ("Unit culture", "culture_belonging"),
    ("Other", None),
]
QUARTERS = [f"{y}Q{q}" for y in (2024, 2025, 2026) for q in (1, 2, 3, 4)][:11]  # 2024Q1..2026Q3


def _w(rng, items, weights):
    return rng.choices(items, weights=weights, k=1)[0]


def _fill(rng, s):
    for k, v in SLOTS.items():
        while "{" + k + "}" in s:
            s = s.replace("{" + k + "}", rng.choice(v), 1)
    return s


class Generator:
    def __init__(self, seed: int = DEFAULT_SEED):
        self.rng = random.Random(seed)
        self.seed = seed
        r = random.Random(seed + 1)
        names = [(f, l) for f in FIRST for l in LAST]
        r.shuffle(names)
        self.roster = names[:400]           # synthetic directory (roster layer)
        self.non_roster = names[400:460]    # e.g. former staff: only cue/NER layers can catch
        self.decoys: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------ decoys
    def _phone(self):
        return self.rng.choice(["(217) 555-01{:02d}", "217-555-01{:02d}", "217.555.01{:02d}", "+1 217 555 01{:02d}"]).format(
            self.rng.randint(0, 99))

    def _decoy_sentence(self, rid):
        rng = self.rng
        f, l = rng.choice(self.non_roster) if rng.random() < 0.2 else rng.choice(self.roster)
        full = f"{f} {l}"
        email = f"{f.lower()}.{l.lower()}{rng.randint(1, 99)}@example.edu"
        phone = self._phone()
        uin = f"65{rng.randint(1000000, 9999999)}"
        kind = rng.choice(["name_email", "name_phone", "intro", "title", "uin", "manager_name", "bare_name"])
        found, themes = [], []
        if kind == "name_email":
            s = f"Please follow up with me, {full}, at {email}."
            found = [("PERSON", full), ("EMAIL", email)]
        elif kind == "name_phone":
            s = f"You can call me at {phone} if you want details. - {full}"
            found = [("PHONE", phone), ("PERSON", full)]
        elif kind == "intro":
            s = f"My name is {full} and I am happy to talk about this."
            found = [("PERSON", full)]
        elif kind == "title":
            hon = rng.choice(["Dr.", "Ms.", "Mr.", "Mx."])
            s = f"Ask {hon} {l} in our office, she has seen the same thing."
            found = [("PERSON", f"{hon} {l}")]
        elif kind == "uin":
            s = f"My UIN is {uin} in case you need to look me up."
            found = [("UIN", uin)]
        elif kind == "manager_name":
            s = f"My supervisor {full} has been unfair to several of us."
            found = [("PERSON", full)]
            themes = ["manager_support"]
        else:
            if (f, l) not in self.roster:
                f, l = rng.choice(self.roster)
                full = f"{f} {l}"
            s = f"{full} has been carrying our team and deserves recognition."
            found = [("PERSON", full)]
            themes = ["recognition"]
        self.decoys.setdefault(rid, []).extend({"type": t, "value": v} for t, v in found)
        return s, themes

    # ---------------------------------------------------------------- comments
    def _comment(self, rid, themes_valence, p_decoy=0.07):
        rng = self.rng
        sents, truth = [], set()
        for th, val in themes_valence:
            kind = "implicit" if rng.random() < 0.12 else val
            sents.append(_fill(rng, rng.choice(T[th][kind])))
            truth.add(th)
        if rng.random() < 0.15:
            sents.append(rng.choice(FILLERS))
        if rng.random() < p_decoy:
            s, extra = self._decoy_sentence(rid)
            sents.insert(rng.randint(0, len(sents)), s)
            truth.update(extra)
        rng.shuffle(sents) if rng.random() < 0.3 else None
        return " ".join(sents), sorted(truth)

    def _pick_themes(self, unit_eff, role_eff, rates):
        rng = self.rng
        out = []
        for th in THEMES:
            p = rates[th]
            if rng.random() < p:
                pneg = min(0.97, max(0.05, P_NEG[th] - 0.08 * (unit_eff + role_eff)))
                out.append((th, "neg" if rng.random() < pneg else "pos"))
        if len(out) > 3:
            rng.shuffle(out)
            out = out[:3]
        return out

    # -------------------------------------------------------------------- WS
    def workplace_satisfaction(self, n=3000):
        rng = self.rng
        rows, truth = [], []
        uw = [u[1] for u in UNITS]
        rw = [r[1] for r in ROLE_FAMILIES]
        for i in range(n):
            wave = 2025 if i < n // 2 else 2026
            u = _w(rng, UNITS, uw)
            r = _w(rng, ROLE_FAMILIES, rw)
            ten = _w(rng, TENURE, TENURE_W)
            rates = dict(BASE_RATE)
            if r[0].startswith("Civil Service - Trades"):
                rates["workload"] += 0.1; rates["pay"] += 0.08
            if r[0] in ("Faculty", "Postdoc/Research Staff"):
                rates["bureaucracy"] += 0.1
            if wave == 2026:
                rates["ai_tools"] += 0.10; rates["remote_hybrid"] += 0.05
            if ten == "20+ yrs":
                rates["relocation_retirement"] += 0.05
            tv = self._pick_themes(u[2], r[2], rates)
            score = 8.6 + u[2] + r[2] + rng.gauss(0, 1.5)
            for th, val in tv:
                score += EFFECT[th][0] if val == "neg" else EFFECT[th][1]
            enps = int(min(10, max(0, round(score))))
            rid = f"R_SYNWS{wave}{i:05d}"
            answered = rng.random() > 0.18  # ~18% leave the comment box empty
            if answered and tv:
                text, th_truth = self._comment(rid, tv)
            elif answered:
                text, th_truth = rng.choice(FILLERS), []
                if rng.random() < 0.07:
                    s, extra = self._decoy_sentence(rid)
                    text, th_truth = f"{text} {s}", extra
            else:
                text, th_truth = "", []
            start = datetime(wave, 3, 1, 8) + timedelta(minutes=rng.randint(0, 60 * 24 * 28))
            rows.append({
                "ResponseId": rid, "StartDate": start.isoformat(sep=" "),
                "EndDate": (start + timedelta(seconds=rng.randint(90, 1500))).isoformat(sep=" "),
                "Finished": "True", "survey_wave": wave, "unit": u[0], "role_family": r[0], "tenure_band": ten,
                "Q_eNPS": enps, "Q_comment": text, "synthetic": "True"})
            truth.append({"ResponseId": rid, "survey": "ws", "themes": ";".join(th_truth),
                          "answered": int(bool(text))})
        return rows, truth

    # ------------------------------------------------------------------ exit
    def exit_survey(self, n=800):
        rng = self.rng
        rows, truth = [], []
        uw = [u[1] for u in UNITS]
        rw = [r[1] for r in ROLE_FAMILIES]
        for i in range(n):
            q = QUARTERS[min(len(QUARTERS) - 1, int(rng.random() * len(QUARTERS)))]
            qi = QUARTERS.index(q)
            u = _w(rng, UNITS, uw)
            r = _w(rng, ROLE_FAMILIES, rw)
            ten = _w(rng, TENURE, EXIT_TENURE_W)
            # reason mix drifts over time: pay/remote share rises, retirement wave in 2025
            w = [18 + qi, 14, 15 + (4 if u[2] < -0.5 else 0), 9, 6 + qi * 0.8,
                 (22 if ten == "20+ yrs" else 1) + (4 if q.startswith("2025") else 0),
                 10, 7, 6]
            reason = _w(rng, EXIT_REASONS, w)
            tv = []
            if reason[1]:
                tv.append((reason[1], "pos" if reason[0] in ("Retirement", "Relocation / family") else "neg"))
            for th in THEMES:
                if th != reason[1] and rng.random() < BASE_RATE[th] * 0.6:
                    tv.append((th, "neg" if rng.random() < P_NEG[th] else "pos"))
            tv = tv[:3]
            rid = f"R_SYNEX{i:05d}"
            answered = rng.random() > 0.12
            text, th_truth = self._comment(rid, tv) if (answered and tv) else ("", [])
            y, qq = int(q[:4]), int(q[-1])
            d = date(y, 3 * qq - 2, 1) + timedelta(days=rng.randint(0, 88))
            rows.append({"ResponseId": rid, "StartDate": f"{d} 10:00:00", "EndDate": f"{d} 10:12:00",
                         "Finished": "True", "separation_quarter": q, "unit": u[0], "role_family": r[0],
                         "tenure_band": ten, "Q_primary_reason": reason[0],
                         "Q_recommend_0_10": int(min(10, max(0, round(5.5 + u[2] + rng.gauss(0, 2.2))))),
                         "Q_comment": text, "synthetic": "True"})
            truth.append({"ResponseId": rid, "survey": "exit", "themes": ";".join(th_truth),
                          "answered": int(bool(text))})
        return rows, truth

    def headcount(self):
        rng = self.rng
        out = []
        for fy in (2025, 2026):
            for u in UNITS:
                hc = int(u[3] * (1 + rng.uniform(-0.03, 0.03)))
                rate = 0.075 - 0.02 * u[2] + rng.uniform(-0.01, 0.01)
                out.append({"fiscal_year": fy, "unit": u[0], "headcount": hc,
                            "separations": max(0, int(round(hc * rate))), "synthetic": "True"})
        return out


QUESTION_TEXT = {
    "Q_eNPS": "How likely are you to recommend [University] as a place to work? (0-10)",
    "Q_comment": "What one change would most improve your work experience? (optional)",
    "Q_primary_reason": "What is the primary reason you are leaving?",
    "Q_recommend_0_10": "How likely are you to recommend [University] as a place to work? (0-10)",
}


def write_qualtrics_csv(path: Path, rows: list[dict]):
    """Qualtrics 'Export Data > CSV' layout: header, question-text row, ImportId row."""
    cols = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerow([QUESTION_TEXT.get(c, c) for c in cols])
        w.writerow([json.dumps({"ImportId": c if c.startswith("Q_") else c.lower()}) for c in cols])
        for r in rows:
            w.writerow([r[c] for c in cols])


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def simulate_gold(truth: list[dict], seed: int, n=400, flip=0.04):
    """SIMULATED gold: coder_A = generator truth, coder_B = truth with per-theme flips.
    Real use replaces this file with two human coders' independent labels."""
    rng = random.Random(seed + 7)
    pool = [t for t in truth if t["answered"]]
    sample = rng.sample(pool, n)
    out = []
    for t in sample:
        a = set(filter(None, t["themes"].split(";")))
        b = set(a)
        for th in THEMES:
            if rng.random() < flip:
                b.symmetric_difference_update({th})
        for coder, labels in (("coder_A_SIMULATED", a), ("coder_B_SIMULATED", b)):
            out.append({"ResponseId": t["ResponseId"], "coder_id": coder, "themes": ";".join(sorted(labels)),
                        "coded_on": "2026-11-06", "codebook_version": "0.1", "synthetic": "True"})
    return out


def main(seed: int = DEFAULT_SEED, out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    (out / "gold").mkdir(exist_ok=True)
    g = Generator(seed)
    ws, ws_truth = g.workplace_satisfaction()
    ex, ex_truth = g.exit_survey()
    hc = g.headcount()
    write_qualtrics_csv(out / "ws_export.csv", ws)
    write_qualtrics_csv(out / "exit_export.csv", ex)
    write_csv(out / "unit_headcount.csv", hc)
    write_csv(out / "roster_names.csv", [{"first": f, "last": l, "synthetic": "True"} for f, l in g.roster])
    write_csv(out / "theme_truth.csv", ws_truth + ex_truth)
    write_csv(out / "gold" / "gold_sample.csv", simulate_gold(ws_truth + ex_truth, seed))
    (out / "decoy_manifest.json").write_text(json.dumps(
        {"synthetic": True, "seed": seed, "decoys": g.decoys}, indent=1), encoding="utf-8")
    (out / "README_SYNTHETIC.txt").write_text(
        "ALL FILES IN THIS FOLDER ARE SYNTHETIC, generated by survey_text/generate_synthetic.py "
        f"with seed {seed}. They contain no real survey responses or people. Names, e-mails "
        "(example.edu), phone numbers (555-01xx) and UINs are fictional decoys used to test redaction.\n",
        encoding="utf-8")
    stats = {"ws": len(ws), "exit": len(ex), "decoy_responses": len(g.decoys),
             "decoy_values": sum(len(v) for v in g.decoys.values())}
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    a = ap.parse_args()
    print(json.dumps(main(a.seed), indent=1))
