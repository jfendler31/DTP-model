# Coach KenPom season table: python3 tools/kp_coach.py "Coach Name" [...] (run from the repo root). Ranks one stat per line with direction labels.
import warnings; warnings.filterwarnings("ignore")
import pandas as pd,glob,sys
def load(k):
    d=pd.concat([pd.read_csv(f) for f in glob.glob(f'data/kenpom/history/{k}_*.csv')])
    if 'ConfOnly' in d.columns: d=d[~d.ConfOnly.astype(str).str.lower().isin(['true','1','y','yes'])]
    return d
R=load('ratings'); ff=load('four-factors'); ms=load('misc-stats')
x=R.merge(ff,on=['Season','TeamName'],suffixes=('','_ff')).merge(ms,on=['Season','TeamName'],suffixes=('','_ms'))
n=x.groupby('Season').TeamName.transform('count')
cols=[('RankAdjEM','AdjEM'),('RankAdjOE','Off eff'),('RankAdjDE','Def eff'),('RankAdjTempo','Tempo (1=fastest)'),
('RankeFG_Pct','Off eFG'),('RankTO_Pct','Off TO% (1=fewest)'),('RankOR_Pct','Off OReb%'),('RankFT_Rate','Off FT rate'),
('RankF3GRate','Off 3PA rate (1=most)'),('RankFG3Pct','Off 3P%'),('RankAvg2PADist','Off 2PA dist (1=shortest)'),
('RankDeFG_Pct','Def eFG allowed (1=lowest)'),('RankDTO_Pct','Def TO forced (1=most)'),('RankDOR_Pct','Def OReb% allowed (1=lowest)'),
('RankDFT_Rate','Def FT rate allowed (1=lowest)'),('RankOppF3GRate','Def 3PA rate allowed (1=fewest)'),('RankOppFG3Pct','Def 3P% allowed (1=lowest)'),
('RankStlRate','Def steal rate'),('RankBlockPct','Def block%')]
for coach in sys.argv[1:]:
    y=x[x.Coach.astype(str).str.contains(coach)].sort_values('Season')
    y=y.assign(N=n[y.index])
    t=pd.DataFrame({f"{s} {tm[:10]}":[int(r[c]) for c,_ in cols]+[int(r['N'])] for s,tm,r in zip(y.Season,y.TeamName,[r for _,r in y.iterrows()])}, index=[l for _,l in cols]+['teams in D-I'])
    print('==',coach); print(t.to_string())
