"""Availability Tracker notes -> data/tracker/player_status.csv (Nov 10).
The 4:15 AM scheduled task reads the tracker's `notes` collection (ArtifactData list, out_dir) and runs:
    python jobs/tracker_export.py <notes_dir>          (notes_dir holds one JSON file per note)
then commits the CSV together with triggers/card.txt, so the card job's override sync sees tonight's tracker.
Columns: id, team (KenPom spelling), team_tracker, player, status, details, back, hidden, updated (ISO), updated_et (YYYY-MM-DD ET)."""
import sys, os, json, glob, datetime as dt
from zoneinfo import ZoneInfo
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from team_names import kp

notes_dir = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else 'data/tracker/player_status.csv'
rows = []
for f in sorted(glob.glob(os.path.join(notes_dir, '*.json'))):
    j = json.load(open(f, encoding='utf-8'))
    d = j.get('data', j)                      # ArtifactData writes {"data": {...}, ...} or the bare document
    if not isinstance(d, dict) or not d.get('player'): continue
    up = str(d.get('updated') or '')
    try: up_et = dt.datetime.fromisoformat(up.replace('Z', '+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    except ValueError: up_et = ''
    tb = str(d.get('team') or '')
    rows.append(dict(id=os.path.basename(f)[:-5], team=kp(tb) or tb, team_tracker=tb, player=d.get('player', ''),
                     status=str(d.get('status') or '').strip(), details=d.get('details') or '', back=d.get('back') or '',
                     hidden=bool(d.get('hidden')), updated=up, updated_et=up_et))
S = pd.DataFrame(rows).sort_values(['team', 'player'])
os.makedirs(os.path.dirname(out), exist_ok=True)
S.to_csv(out, index=False)
unm = sorted(set(S.loc[S.team == S.team_tracker, 'team_tracker']) - set(pd.read_csv('data/prior_2026-27.csv').team))
print(f'{len(S)} tracker notes -> {out}; statuses {S[~S.hidden].status.value_counts().to_dict()}; unmapped teams {unm}')
