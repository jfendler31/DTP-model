"""Data pull for a game read (Nov 13, 2026). Run from the repo root:
    python3 tools/read_pull.py "<Away>" "<Home>" [YYYY-MM-DD]     (KenPom team names; date defaults to the newest card)
Prints the card row, ratings and ranks, scoreboard (composite / opponent-adjusted scoreboard / blend, 3P and FT luck),
override and tracker rows, each system's spread on our scale, KenPom today and FanMatch, coaches, continuity/experience/height,
each team's D-I game log with shooting splits and four-factor counts, closes and margins, minutes by game, EvanMiya BPRs,
and three-point luck against the roster's own shooting history. Then run tools/kp_coach.py, jobs/shotmix_matchup.py and
jobs/roles.py --no-build --short --team for the rest of the fixed read format."""
import pandas as pd, numpy as np, glob, json, sys
D=sys.argv[3] if len(sys.argv)>3 else sorted(glob.glob('cards/card_2026-*.csv'))[-1][-14:-4]
newest=lambda pat: sorted(glob.glob(pat))[-1]
c=pd.read_csv(f'cards/card_{D}.csv'); r=pd.read_csv('data/ratings_current.csv').set_index('team'); r['ins_rank']=r.z_inseason.rank(ascending=False); r['prior_rank']=r.z_prior.rank(ascending=False)
sb=pd.read_csv(f'data/ratings/scoreboard_{D}.csv').set_index('team'); p=pd.read_csv('data/prior_2026-27.csv').set_index('team'); HC=pd.read_csv('data/kp_hca.csv').set_index('team').hca
k=pd.read_csv(newest('data/kenpom/ratings_2026-*.csv') if not glob.glob(f'data/kenpom/ratings_{D}.csv') else f'data/kenpom/ratings_{D}.csv'); k['z']=(k.AdjEM-k.AdjEM.mean())/k.AdjEM.std(ddof=0); K=k.set_index('TeamName')
h=pd.read_csv(newest('data/kenpom/height_2026-*.csv')).set_index('TeamName'); o=pd.read_csv('data/overrides.csv'); t=pd.read_csv('data/tracker/player_status.csv'); fm=pd.read_csv(f'data/kenpom/fanmatch_{D}.csv') if glob.glob(f'data/kenpom/fanmatch_{D}.csv') else pd.DataFrame(columns=['Home','Visitor'])
d=pd.concat([pd.read_csv(f,low_memory=False) for f in glob.glob('data/players/players_2026-*.csv')]).drop_duplicates(['gameId','athleteId'])
X={v.strip():k_ for k_,v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
gl=pd.concat([pd.read_csv(f) for f in glob.glob('data/grades/grade_2026-*.csv')])
e=pd.read_csv('data/evanmiya/ratings_2026-27.csv'); hist=pd.concat([pd.read_csv(f'data/players/history/season_stats_{y}.csv',low_memory=False) for y in range(2022,2027)])
A,H=sys.argv[1],sys.argv[2]; g=c[c.home.eq(H)|c.away.eq(H)].iloc[0]; neutral=g.venue!='H'; hca=0 if neutral else HC[H]
print(g[['away','home','tip_ET','venue','market_home_spread','n_books','model_home_spread','model_home_spread_adj','edge_size_adj','tier','notes','total']].to_string())
print(r.loc[[A,H],['n_games','method','lam','z_prior','z_inseason','move_pts','prior_rank','ins_rank']].round(2).to_string())
print(sb.loc[[A,H],['raw_vs_close','luck_3p','luck_ft_own','luck_ft_opp','adj_vs_close','composite_move','sb_move_adj','blend_move']].round(1).to_string())
print(o[o.team.isin([A,H])].iloc[:,:6].to_string()); print(t[t.team.isin([A,H])][['team','player','status','details','updated_et','hidden']].to_string())
for s in ['z_em','z_kp','z_tv','z_prior']: print(s, round(-(9.5*(p[s][g.home]-p[s][g.away])+hca),1))
print('KP today',round(-(9.5*(K.z[g.home]-K.z[g.away])+hca),1),'| coaches',K.Coach[A],'|',K.Coach[H],'| ranks',K.RankAdjEM[A],K.RankAdjEM[H],'HCA',hca,'| KP O/D ranks',[(x,int(K.RankAdjOE[x]),int(K.RankAdjDE[x]),round(K.AdjTempo[x],1)) for x in (A,H)]); print(fm[fm.Home.eq(g.home)|fm.Visitor.eq(g.home)].iloc[:,:12].to_string(index=False))
for x in (A,H): print(x,'cont',h.Continuity[x],int(h.RankContinuity[x]),'exp',int(h.ExpRank[x]),'hgt',int(h.AvgHgtRank[x]))
for x in (A,H):
    nm=X.get(x,x); y=d[d.team==nm]
    q=y.groupby(['date_ET','gameId','opponent','opponentConference','isHome'],dropna=False).agg(pts=('points','sum'),tpm=('threePointFieldGoals.made','sum'),tpa=('threePointFieldGoals.attempted','sum'),p2m=('twoPointFieldGoals.made','sum'),p2a=('twoPointFieldGoals.attempted','sum'),fta=('freeThrows.attempted','sum'),to=('turnovers','sum'),orb=('rebounds.offensive','sum'),pace=('gamePace','first')).reset_index()
    oq=d[d.gameId.isin(q.gameId)&(d.team!=nm)].groupby('gameId').agg(opp=('points','sum'),otpm=('threePointFieldGoals.made','sum'),otpa=('threePointFieldGoals.attempted','sum'),o2m=('twoPointFieldGoals.made','sum'),o2a=('twoPointFieldGoals.attempted','sum'),ofta=('freeThrows.attempted','sum'),oto=('turnovers','sum'),oorb=('rebounds.offensive','sum'))
    q=q.join(oq,on='gameId'); q['3']=q.tpm.astype(str)+'/'+q.tpa.astype(str); q['o3']=q.otpm.astype(str)+'/'+q.otpa.astype(str); q['2']=q.p2m.astype(str)+'/'+q.p2a.astype(str); q['o2']=q.o2m.astype(str)+'/'+q.o2a.astype(str)
    print('\n',x,'=',nm); print(q[['date_ET','opponent','opponentConference','isHome','pts','opp','2','o2','3','o3','to','oto','orb','oorb','fta','ofta','pace']].to_string(index=False))
    print(gl[(gl.home==x)|(gl.away==x)][['date','away','home','close','home_margin']].to_string(index=False))
    m=y.pivot_table(index='name',columns='date_ET',values='minutes',aggfunc='sum').fillna(0); print(m.assign(tot=m.sum(axis=1)).sort_values('tot',ascending=False).head(12).round(0).to_string())
    em=e[(e.team==nm)|(e.team==x)].sort_values('bpr',ascending=False).head(10); print(em[['name','bpr','bpr_source']].to_string(index=False))
    yy=y.groupby(['athleteId','name'])[['threePointFieldGoals.made','threePointFieldGoals.attempted']].sum().reset_index(); yy.columns=['id','name','m','a']; ex=0
    for r_ in yy.itertuples():
        hh=hist[hist.athleteId==r_.id]; ex+=r_.a*(hh['threePointFieldGoals.made'].sum()+33.5)/(hh['threePointFieldGoals.attempted'].sum()+100)
    print(f' 3P {int(yy.m.sum())}/{int(yy.a.sum())} = {yy.m.sum()/yy.a.sum():.1%}, roster-history exp {ex/yy.a.sum():.1%} -> {3*(yy.m.sum()-ex):+.0f} pts')
