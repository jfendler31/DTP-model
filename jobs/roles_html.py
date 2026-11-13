"""Role cards as one self-contained HTML page in the Box Out Daily look (Source Serif/Sans, #b4491f accent).

Reads data/roles/roles_current.csv + assist_pairs.csv (jobs/roles.py) and KenPom conferences; writes
data/roles/role_cards.html. One team at a time (search box, #team-slug in the URL), or every player in D-I with a chosen label.
usage: python3 jobs/roles_html.py [--out PATH]
"""
import argparse, json, re, datetime as dt
import pandas as pd

ROLES = 'data/roles'
LABEL_ORDER = ['lead engine', 'connector', 'playmaker (loose)', 'self-creating scorer', 'downhill creator', 'slasher', 'spot-up shooter',
               'pull-up shooter', 'off-dribble jumpers', 'stretch big', 'rim runner', 'post scorer', 'interior scorer', 'glass', 'putbacks',
               'rim protector', 'pickpocket', 'transition', 'low-usage role player', 'balanced']
LABEL_DEF = {
    'lead engine': 'Usage 23+, assist rate 20+, 55%+ of made shots unassisted',
    'connector': 'Assist rate 20+, usage under 23, turnover rate under 22',
    'playmaker (loose)': 'Connector profile with a turnover rate of 22+',
    'self-creating scorer': 'Usage 22+, 60%+ of made shots unassisted, assist rate under 20',
    'downhill creator': 'Non-big, usage 22+, 30%+ of shots at the rim, 60%+ of rim makes unassisted',
    'slasher': 'Non-big, 45%+ of shots at the rim, 60%+ of rim makes unassisted',
    'spot-up shooter': '55%+ of shots are threes, 75%+ of made threes assisted',
    'pull-up shooter': 'Non-big, 40%+ of shots are threes, under 50% of made threes assisted',
    'off-dribble jumpers': 'Non-big, pull-ups plus floaters 25%+ of shots',
    'stretch big': 'Big, 35%+ of shots are threes',
    'rim runner': 'Big, 60%+ of shots at the rim, 50%+ of rim makes assisted',
    'post scorer': 'Hooks and turnarounds 20%+ of shots, usage 16+',
    'interior scorer': 'Big, 50%+ of shots at the rim, under 50% of rim makes assisted, usage 18+',
    'glass': 'Offensive rebound rate 10%+',
    'putbacks': '2+ putbacks per 40 (shot within 4 seconds of his own offensive rebound)',
    'rim protector': '2.5+ blocks per 40',
    'pickpocket': '3.5+ steals per 40',
    'transition': '4+ transition shots per 40 (within 7 seconds of a defensive rebound or steal)',
    'low-usage role player': 'Usage under 14, nothing else applies',
    'balanced': 'Usage 14+, no clear profile',
}


THIN = {  # label -> (column, minimum, what it counts) — below the minimum the tag shows faded
    'lead engine': ('n_fgm_raw', 10, 'made shots'), 'self-creating scorer': ('n_fgm_raw', 10, 'made shots'),
    'downhill creator': ('n_rim_m_raw', 6, 'rim makes'), 'slasher': ('n_rim_m_raw', 6, 'rim makes'),
    'rim runner': ('n_rim_m_raw', 6, 'rim makes'), 'interior scorer': ('n_rim_m_raw', 6, 'rim makes'),
    'spot-up shooter': ('n_three_m_raw', 6, 'made threes'), 'pull-up shooter': ('n_three_m_raw', 6, 'made threes'),
    'connector': ('min_lev', 60, 'competitive minutes'), 'playmaker (loose)': ('min_lev', 60, 'competitive minutes'),
    'stretch big': ('n_fga_raw', 20, 'shots'), 'post scorer': ('n_fga_raw', 20, 'shots'), 'off-dribble jumpers': ('n_fga_raw', 20, 'shots'),
    'balanced': ('n_fga_raw', 20, 'shots'), 'low-usage role player': ('n_fga_raw', 20, 'shots'),
    'glass': ('min_lev', 80, 'competitive minutes'), 'putbacks': ('min_lev', 80, 'competitive minutes'),
    'rim protector': ('min_lev', 80, 'competitive minutes'), 'pickpocket': ('min_lev', 80, 'competitive minutes'),
    'transition': ('min_lev', 80, 'competitive minutes'),
}


def thin(r, labs):
    out = []
    for l in labs:
        if l in THIN:
            c, m, what = THIN[l]; v = getattr(r, c)
            if pd.notna(v) and v < m: out.append([l, f'{int(round(v))} {what}; needs {m}'])
    return out


def slug(t):
    return re.sub(r'[^a-z0-9]+', '-', str(t).lower().replace('&', ' and ')).strip('-')


def ht(h):
    if pd.isna(h): return ''
    h = int(round(h)); return f"{h // 12}'{h % 12}\""


def build(out):
    S = pd.read_csv(f'{ROLES}/roles_current.csv')
    A = pd.read_csv(f'{ROLES}/assist_pairs.csv')
    try:
        K = pd.read_csv('data/kenpom/ratings_current.csv'); conf = dict(zip(K.TeamName, K.ConfShort))
    except Exception:
        conf = {}
    S = S[S.min_lev >= 3].copy()
    teams = sorted(S.team.unique())
    tix = {t: i for i, t in enumerate(teams)}
    gp = S.groupby('team').gp.max()
    T = [[t, conf.get(t, ''), slug(t), int(gp[t])] for t in teams]
    r1 = lambda v, d=1: None if pd.isna(v) else round(float(v), d)
    pct = lambda v: None if pd.isna(v) else round(100 * float(v))
    P = []
    for r in S.sort_values(['team', 'min_lev'], ascending=[True, False]).itertuples():
        labs = [] if pd.isna(r.labels) else [l.strip() for l in str(r.labels).split(';') if l.strip()]
        P.append([tix[r.team], r.player, '' if pd.isna(r.pos) else str(r.pos)[0], ht(r.ht), int(r.gp), r1(r.min_lev), r1(r.usg), r1(r.ast_pct), r1(r.to_pct),
                  pct(r.efg), None if pd.isna(r.astd) else round(100 * (1 - r.astd)), pct(r.rim_sh), pct(r.mid_sh), pct(r.three_sh),
                  pct(r.rim_astd), pct(r.three_astd), r1(r.or_pct), r1(r.stl40), r1(r.blk40), labs,
                  int(r.n_fga_raw), int(r.n_fgm_raw), thin(r, labs)])
    A = A[A.team.isin(tix)].sort_values(['team', 'n'], ascending=[True, False]).groupby('team').head(8)
    AS = [[tix[r.team], r.ast_name, r.player, r.zone, round(float(r.n), 1)] for r in A.itertuples()]
    asof = (dt.date.today() - dt.timedelta(days=1)).strftime('%b. %-d')
    data = dict(T=T, P=P, A=AS, L=[[l, LABEL_DEF[l]] for l in LABEL_ORDER], asof=asof)
    html = TEMPLATE.replace('__DATA__', json.dumps(data, separators=(',', ':'), ensure_ascii=False)).replace('__ASOF__', asof)
    open(out, 'w').write(html)
    print(f'{out}: {len(T)} teams, {len(P)} players, {len(html) // 1024} KB')


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Role Cards — Box Out Daily</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&family=Source+Serif+4:ital,wght@0,600;0,700;1,700&display=swap">
<style>
:root{--acc:#b4491f;--ink:#111;--dim:#555;--rule:#cfcfcf;--alt:#f1f1ee;--mid:#9a9a94;--sans:'Source Sans 3','Helvetica Neue',Helvetica,sans-serif;--serif:'Source Serif 4',Georgia,serif}
body{margin:0;background:#fff;color:var(--ink);font-family:var(--sans)}
a{color:var(--ink)}a:hover{color:var(--acc)}
.wrap{max-width:1180px;margin:0 auto;padding:28px 24px 40px;display:flex;flex-direction:column;gap:22px}
.mast{border-top:4px solid var(--acc);padding-top:12px;display:flex;flex-direction:column;gap:8px}
.brand{font-family:var(--serif);font-weight:800;font-size:26px;text-decoration:none}
.brand span{background:var(--ink);color:#fff;padding:0 6px;border-radius:2px}
.nav{display:flex;gap:22px;flex-wrap:wrap;font-size:15px;border-bottom:2px solid var(--ink);align-items:center}
.nav span{padding:11px 0}.nav .on{border-bottom:3px solid var(--acc);font-weight:700}
h1{font-family:var(--serif);font-style:italic;font-weight:700;font-size:40px;margin:0}
h2{font-family:var(--serif);font-size:22px;margin:0}
.dim{color:var(--dim)}
.bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 14px;background:var(--alt)}
.bar input,.bar select{font:inherit;font-size:15px;padding:8px 10px;border:1px solid var(--ink);background:#fff;min-height:44px;box-sizing:border-box}
.bar input{width:260px;max-width:100%}
.bar button{font:inherit;font-size:15px;font-weight:700;border:2px solid var(--ink);background:#fff;padding:8px 14px;min-height:44px;cursor:pointer}
.bar button:hover{color:var(--acc);border-color:var(--acc)}
.head{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;flex-wrap:wrap}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:15px;font-variant-numeric:tabular-nums}
th{text-align:right;border-bottom:1px solid var(--ink);padding:0;white-space:nowrap;font-size:13px;font-weight:700;vertical-align:bottom}
th button{all:unset;cursor:pointer;display:block;padding:8px 8px}
th button:focus-visible{outline:2px solid var(--acc);outline-offset:-2px}
th[aria-sort] button{color:var(--acc)}th[aria-sort=ascending] button::after{content:" ▴"}th[aria-sort=descending] button::after{content:" ▾"}
th.grp{border-bottom:none;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--dim);text-align:center;padding:0 8px 2px}
td{padding:8px;text-align:right;border-bottom:1px solid var(--rule);white-space:nowrap;vertical-align:top}
tr.alt td{background:var(--alt)}
.l{text-align:left}
td.pl{white-space:normal;min-width:210px}
.nm{font-weight:700;font-size:16px}.meta{font-size:13px;color:var(--dim)}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.chip{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:1px 6px;border:1px solid var(--ink);border-radius:2px;line-height:1.5}
.chip.k{background:var(--ink);color:#fff}
.chip.a{border-color:var(--acc);color:var(--acc)}
.chip.hit{background:var(--acc);border-color:var(--acc);color:#fff}
.chip.lim{border-color:var(--rule);color:var(--dim)}
.chip.thin{background:#fff!important;color:var(--dim)!important;border:1px dashed var(--mid)!important;font-weight:600}
.chip.thin::after{content:" ?";font-weight:700}
tr.limrow td{color:var(--dim)}
.hi{font-weight:700}
.sm{display:flex;flex-direction:column;gap:3px;min-width:150px}
.smb{display:flex;height:12px;width:150px;background:var(--alt)}
.smb i{display:block;height:100%}
.r{background:var(--acc)}.m{background:var(--mid)}.t{background:var(--ink)}
.smt{font-size:12px;color:var(--dim);display:flex;gap:8px}
.astd{font-size:12px;color:var(--dim)}
.key{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--dim);align-items:center}
.key i{display:inline-block;width:12px;height:12px;vertical-align:-1px;margin-right:4px}
.links{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:48px}
.lk{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid var(--rule);font-size:15px}
.lk .z{font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--dim)}
.note{font-size:14px;line-height:1.5;padding:10px 14px;border-left:3px solid var(--acc);max-width:95ch}
details summary{cursor:pointer;font-weight:700;font-size:15px}
.defs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:48px;margin-top:10px}
.def{padding:6px 0;border-bottom:1px solid var(--rule);font-size:14px}
.def b{display:inline-block;min-width:170px}
.foot{font-size:13px;border-top:2px solid var(--ink);padding-top:10px}
.empty{padding:30px 0;font-size:16px}
@media (max-width:760px){.wrap{padding:18px 14px 30px}h1{font-size:32px}.hc{display:none}.links,.defs{grid-template-columns:1fr}
 table{font-size:14px}td,th button{padding-left:5px;padding-right:5px}td.pl{min-width:150px}.smb{width:110px}.sm{min-width:110px}.def b{min-width:0;display:block}}
</style></head><body><div class="wrap">
<div class="mast"><div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap"><span class="brand"><span>Box</span> Out Daily</span><div class="dim" style="font-size:14px">Who does what, from every D1 play-by-play.</div></div>
<div class="nav"><span class="on">Role cards</span><span class="dim">Competitive possessions only · through __ASOF__</span></div></div>

<div class="bar">
 <input id="q" type="text" list="teams" placeholder="Team name…" aria-label="Team name" autocomplete="off">
 <datalist id="teams"></datalist>
 <select id="lab" aria-label="Find a role"><option value="">Find a role across D1…</option></select>
 <select id="conf" aria-label="Conference" hidden><option value="">All conferences</option></select>
 <span id="cnt" class="dim" style="font-size:14px"></span>
</div>

<div id="view"></div>

<div class="note">Every second of floor time is weighted by how live the game was: full weight while the leading team's win probability is 95% or lower, none at 99.9%+, scaled in between. Min is those competitive minutes, season to date. Usage, assist rate and turnover rate are per possession. <b>Self</b> is the share of a player's made shots nobody assisted. <b>Shot mix</b> splits his field-goal attempts into rim, midrange and three; the small numbers under it are the share of his rim and three makes that were assisted. Players under 20 competitive minutes or 6 shots are marked limited sample. <b>Shots</b> are raw field-goal attempts (all minutes) with makes underneath. A dashed tag with a question mark rests on a thin sample: under 10 made shots for lead engine and self-creating scorer, 6 rim makes for the rim tags, 6 made threes for the shooter tags, 20 shots for the shot-type tags, 60 competitive minutes for the passing tags and 80 for glass, putbacks and the defensive tags. Hover a dashed tag for its count.</div>

<details><summary>What each role means</summary><div class="defs" id="defs"></div></details>

<div class="foot dim">Built from CollegeBasketballData.com play-by-play. Roles are first-pass cutoffs on a few games and will settle as teams play more.</div>
</div>
<script>
const D=__DATA__;
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const KEY=new Set(['lead engine','connector','playmaker (loose)','self-creating scorer','downhill creator']);
const ACC=new Set(['spot-up shooter','pull-up shooter','slasher','stretch big','rim runner','post scorer','interior scorer','off-dribble jumpers']);
const bySlug={},byName={};D.T.forEach((t,i)=>{bySlug[t[2]]=i;byName[t[0].toLowerCase()]=i;});
$('teams').innerHTML=D.T.map(t=>'<option value="'+esc(t[0])+'">').join('');
$('lab').innerHTML+=D.L.map(l=>'<option value="'+esc(l[0])+'">'+esc(l[0])+'</option>').join('');
$('defs').innerHTML=D.L.map(l=>'<div class="def"><b>'+esc(l[0])+'</b>'+esc(l[1])+'</div>').join('');
const confs=[...new Set(D.T.map(t=>t[1]).filter(Boolean))].sort();
$('conf').innerHTML+=confs.map(c=>'<option>'+esc(c)+'</option>').join('');
// player row: 0 team,1 name,2 pos,3 ht,4 gp,5 min,6 usg,7 ast,8 to,9 efg,10 self,11 rim,12 mid,13 three,14 rimA,15 threeA,16 or,17 stl,18 blk,19 labels
const f1=v=>v==null?'–':v.toFixed(1), f0=v=>v==null?'–':String(v);
function chips(L,hit,T){const th=Object.fromEntries(T||[]);return '<div class="chips">'+L.map(l=>{let c='chip';if(l==='limited sample')c+=' lim';else if(th[l])c+=' thin';else if(l===hit)c+=' hit';else if(KEY.has(l))c+=' k';else if(ACC.has(l))c+=' a';
 return '<span class="'+c+'"'+(th[l]?' title="Thin sample: '+esc(th[l])+'"':'')+'>'+esc(l)+'</span>';}).join('')+'</div>';}
function mix(p){const r=p[11]||0,m=p[12]||0,t=p[13]||0;
 return '<div class="sm"><div class="smb" role="img" aria-label="Rim '+r+'%, mid '+m+'%, three '+t+'%"><i class="r" style="width:'+r+'%"></i><i class="m" style="width:'+m+'%"></i><i class="t" style="width:'+t+'%"></i></div>'+
 '<div class="smt"><span>'+r+' / '+m+' / '+t+'</span></div><div class="astd">ast: rim '+(p[14]==null?'–':p[14]+'%')+' · 3 '+(p[15]==null?'–':p[15]+'%')+'</div></div>';}
const COLS=[ // key index, label, class, default dir, group
 [1,'Player','l',1,''],[5,'Min','',-1,''],[6,'Usg','',-1,'Creation'],[7,'Ast%','',-1,'Creation'],[8,'TO%','hc',-1,'Creation'],[10,'Self','',-1,'Creation'],
 [20,'Shots','',-1,'Scoring'],[9,'eFG','',-1,'Scoring'],[13,'Shot mix','l',-1,'Scoring'],[16,'OR%','hc',-1,'Activity'],[17,'Stl/40','hc',-1,'Activity'],[18,'Blk/40','hc',-1,'Activity']];
let st={k:5,dir:-1};
function cell(p,k,national){
 switch(k){
  case 1:return '<td class="l pl"><div class="nm">'+esc(p[1])+'</div><div class="meta">'+(national?'<a href="#'+D.T[p[0]][2]+'">'+esc(D.T[p[0]][0])+'</a> · ':'')+[p[2],p[3]].filter(Boolean).join(' · ')+(p[2]||p[3]?' · ':'')+p[4]+' gp</div>'+chips(p[19],$('lab').value,p[22])+'</td>';
  case 5:return '<td>'+f1(p[5])+'</td>';
  case 6:return '<td class="'+(p[6]>=22?'hi':'')+'">'+f1(p[6])+'</td>';
  case 7:return '<td class="'+(p[7]>=20?'hi':'')+'">'+f1(p[7])+'</td>';
  case 8:return '<td class="hc">'+f1(p[8])+'</td>';
  case 10:return '<td>'+(p[10]==null?'–':p[10]+'%')+'</td>';
  case 20:return '<td>'+p[20]+'<div class="astd">'+p[21]+' made</div></td>';
  case 9:return '<td>'+f0(p[9])+'</td>';
  case 13:return '<td class="l">'+mix(p)+'</td>';
  case 16:return '<td class="hc">'+f1(p[16])+'</td>';
  case 17:return '<td class="hc">'+f1(p[17])+'</td>';
  case 18:return '<td class="hc">'+f1(p[18])+'</td>';}}
function table(rows,national){
 const lim=p=>p[19].includes('limited sample');
 rows=rows.slice().sort((a,b)=>{if(!national&&lim(a)!==lim(b))return lim(a)?1:-1;const A=a[st.k],B=b[st.k];
  const c=(A==null?-1e9:(typeof A==='string'?0:A))-(B==null?-1e9:(typeof B==='string'?0:B));return (typeof A==='string'?A.localeCompare(B):c)*st.dir||b[5]-a[5];});
 const grp=[['',2],['Creation',4],['Scoring',3],['Activity',3]];
 const g='<tr class="hc">'+grp.map(([n,s],i)=>'<th class="grp'+(i===3?' hc':'')+'" colspan="'+(i===3?3:s)+'">'+n+'</th>').join('')+'</tr>';
 const h='<tr>'+COLS.map(c=>'<th class="'+c[2]+'" data-k="'+c[0]+'"'+(st.k===c[0]?' aria-sort="'+(st.dir>0?'ascending':'descending')+'"':'')+'><button type="button">'+c[1]+'</button></th>').join('')+'</tr>';
 const b=rows.map((p,i)=>'<tr class="'+(i%2?'alt ':'')+(lim(p)?'limrow':'')+'">'+COLS.map(c=>cell(p,c[0],national)).join('')+'</tr>').join('');
 return '<div class="scroll"><table><thead>'+g+h+'</thead><tbody>'+b+'</tbody></table></div>';}
const key='<div class="key"><span><i class="r"></i>Rim</span><span><i class="m"></i>Midrange</span><span><i class="t"></i>Three</span><span>Bold: usage 22+ or assist rate 20+</span><span><span class="chip thin" style="font-size:10px">tag</span> thin sample</span></div>';
function teamView(i){
 const t=D.T[i],P=D.P.filter(p=>p[0]===i),A=D.A.filter(a=>a[0]===i);
 const links=A.length?'<div style="display:flex;flex-direction:column;gap:8px"><h2>Who sets up whom</h2><div class="links">'+
  A.map(a=>'<div class="lk"><span><b>'+esc(a[1])+'</b> → '+esc(a[2])+' <span class="z">'+esc(a[3]==='three'?'three':a[3]==='rim'?'rim':'mid')+'</span></span><span class="dim">'+a[4].toFixed(a[4]%1?1:0)+'</span></div>').join('')+
  '</div><div class="dim" style="font-size:13px">Assisted makes, weighted by competitive time.</div></div>':'';
 return '<div style="display:flex;flex-direction:column;gap:16px"><div class="head"><div style="display:flex;flex-direction:column;gap:4px"><h1>'+esc(t[0])+'</h1>'+
  '<div class="dim" style="font-size:15px">'+(t[1]?esc(t[1])+' · ':'')+t[3]+' D1 game'+(t[3]===1?'':'s')+' · '+P.length+' players</div></div>'+key+'</div>'+table(P,false)+links+'</div>';}
function labelView(l){
 const c=$('conf').value;
 const P=D.P.filter(p=>p[19].includes(l)&&(!c||D.T[p[0]][1]===c));
 const def=(D.L.find(x=>x[0]===l)||['',''])[1];
 $('cnt').textContent=P.length+' players';
 return '<div style="display:flex;flex-direction:column;gap:16px"><div class="head"><div style="display:flex;flex-direction:column;gap:4px"><h1 style="text-transform:capitalize">'+esc(l)+'</h1>'+
  '<div class="dim" style="font-size:15px">'+esc(def)+'</div></div>'+key+'</div>'+(P.length?table(P,true):'<div class="empty dim">No players with this role'+(c?' in '+esc(c):'')+'.</div>')+'</div>';}
function render(){
 const h=location.hash.slice(1);let html;$('cnt').textContent='';
 const lab=$('lab').value;$('conf').hidden=!lab;
 if(lab){html=labelView(lab);}
 else if(h&&bySlug[h]!=null){html=teamView(bySlug[h]);$('q').value=D.T[bySlug[h]][0];}
 else{html='<div class="empty"><h1>Role cards</h1><p class="dim">Type a team above, or pick a role to see every player in D1 who fits it. '+D.T.length+' teams, '+D.P.length+' players.</p></div>';}
 $('view').innerHTML=html;
 document.querySelectorAll('#view th[data-k] button').forEach(btn=>btn.addEventListener('click',()=>{const k=+btn.parentNode.dataset.k;const c=COLS.find(x=>x[0]===k);
  if(st.k===k)st.dir*=-1;else{st.k=k;st.dir=c[3];}render();}));}
$('q').addEventListener('input',()=>{const i=byName[$('q').value.trim().toLowerCase()];if(i!=null){$('lab').value='';st={k:5,dir:-1};
 if(location.hash.slice(1)!==D.T[i][2])location.hash=D.T[i][2];else render();}});
$('q').addEventListener('keydown',e=>{if(e.key==='Enter'){const s=$('q').value.trim().toLowerCase();const i=D.T.findIndex(t=>t[0].toLowerCase().includes(s));if(s&&i>=0){$('lab').value='';location.hash=D.T[i][2];}}});
$('lab').addEventListener('change',()=>{st={k:5,dir:-1};render();});
$('conf').addEventListener('change',render);
window.addEventListener('hashchange',()=>{$('lab').value='';render();});
if(!location.hash)try{const s=localStorage.getItem('rc_team');if(s&&bySlug[s]!=null)history.replaceState(null,'','#'+s);}catch(e){}
window.addEventListener('hashchange',()=>{try{localStorage.setItem('rc_team',location.hash.slice(1));}catch(e){}});
render();
</script></body></html>"""

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default=f'{ROLES}/role_cards.html')
    build(ap.parse_args().out)
