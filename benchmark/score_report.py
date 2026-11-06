"""Summarize manually reviewed scorecards without converting unknowns to scores."""
import json
from pathlib import Path


def summarize(card):
    earned=0.;tested=0
    for row in card['criteria']:
        rating=row['rating']
        if rating is None:continue
        if type(rating) not in (int,float) or not 0<=rating<=5:
            raise ValueError('Rating must be null or a number between 0 and 5')
        if not row.get('evidence'):raise ValueError('A rating requires supporting evidence')
        earned+=row['weight']*rating/5;tested+=row['weight']
    assert sum(r['weight'] for r in card['criteria'])==100
    return {'platform':card['platform'],'track':card['track'],'provisional_points':round(earned,2) if tested else None,
      'tested_weight':tested,'total_weight':100,'rating_status':'not_tested' if not tested else 'provisional',
      'gate_results':card['gate_results'],'production_ready':'not established'}


if __name__=='__main__':
    for p in sorted((Path(__file__).resolve().parent/'scorecards').glob('*.json')):
        print(json.dumps(summarize(json.loads(p.read_text()))))
