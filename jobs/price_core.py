"""Absence pricing (runbook §3 'Price an injury / status'), shared by tools/price_tracker.py and the 4:15 sync (Nov 14, 2026).
value = EvanMiya team_value() with vs without the player (top-8 minutes curve), cascading on top of the team's active overrides and
anything priced earlier in the same run; player missing from EvanMiya -> his Torvik gBPM as a stand-in BPR (said so in the text).
priced share = 0.45 x (EvanMiya team rating still counts him: Oct 20 player file vs EM team bpr, fitted line) + 0.35 (KenPom: unknown)
+ 0.20 x (Torvik projected him minutes). In-season overlap: x (1 - lam x share of the team's D-I games he missed), lam = N/(N+8).
spread = value / 10.35 x 9.5 x share x overlap x weight; delta_pts (card / prior scale) = value / 10.35 x SD(prior_pts) x the same.
Player matching uses team_names.match_name (exact, then same last name + compatible first name, unique)."""
import os, sys, glob
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from absence_sweep import team_value, make_fixer
from team_names import pn, kp, match_name

TV_DEFAULT = 'data/torvik/torvik_fragility_players_all_2026-10-23.csv'
MAN = {'Miami (Fla.)': 'Miami FL', 'Florida International': 'FIU'}


class Pricer:
    def __init__(self, D, tv_file=TV_DEFAULT, box=None):
        self.D = D
        self.P = pd.read_csv('data/prior_2026-27.csv').set_index('team')
        self.SD = self.P.prior_pts.std()
        fix = make_fixer(self.P.index)
        tm = lambda t: MAN.get(t) or fix(t)
        self.E = pd.read_csv('data/evanmiya/ratings_2026-27.csv'); self.E['kp'] = self.E.team.map(tm)
        self.O20 = pd.read_csv('data/evanmiya/player_ratings_2026-10-20.csv'); self.O20['kp'] = self.O20.team.map(tm)
        self.TV = pd.read_csv(tv_file) if os.path.exists(tv_file) else pd.DataFrame(columns=['team', 'player', 'min_pct', 'gbpm'])
        self.R = pd.read_csv('data/ratings_current.csv').set_index('team')
        tv0 = self.O20.groupby('kp').bpr.apply(lambda s: team_value(list(s)))
        j = pd.concat([tv0, self.P.bpr], axis=1, keys=['tv', 'em']).dropna()
        self.b1, self.b0 = np.polyfit(j.tv, j.em, 1)
        OV = pd.read_csv('data/overrides.csv', dtype=str).fillna('')
        act = OV[(OV.expires.isin(['', 'until cleared', 'season']) | (OV.expires >= D)) & ~OV.player.str.startswith('(venue)')]
        self.outs = {t: list(g.player) for t, g in act.groupby('team')}
        # player-game minutes: rotation store (all D-I games, through two days ago) + any recent box rows passed in
        parts = []
        if os.path.exists('data/rotation/player_games.csv'):
            pg = pd.read_csv('data/rotation/player_games.csv', usecols=['gameId', 'team', 'opponent', 'athlete', 'min_raw'])
            parts.append(pd.DataFrame({'gameId': pg.gameId, 'team_kp': pg.team.map(lambda t: kp(t) or t), 'name': pg.athlete, 'minutes': pg.min_raw,
                                       'd1': pg.opponent.map(lambda t: kp(t) is not None)}))
        for f in glob.glob('data/players/players_2026-11-*.csv'):
            b = pd.read_csv(f, low_memory=False, usecols=lambda c: c in ('gameId', 'team', 'name', 'minutes', 'opponentConference'))
            parts.append(pd.DataFrame({'gameId': b.gameId, 'team_kp': b.team.map(lambda t: kp(t) or t), 'name': b.name, 'minutes': b.minutes,
                                       'd1': b.opponentConference.notna()}))
        if box is not None and len(box):
            parts.append(pd.DataFrame({'gameId': box.gameId, 'team_kp': box.team_kp, 'name': box.name, 'minutes': pd.to_numeric(box.minutes, errors='coerce'),
                                       'd1': box.opponentConference.notna() if 'opponentConference' in box else True}))
        self.box = pd.concat(parts, ignore_index=True).drop_duplicates(['gameId', 'team_kp', 'name']) if parts else pd.DataFrame(columns=['gameId', 'team_kp', 'name', 'minutes', 'd1'])

    def price(self, team, player, w=1.0, register=True):
        """Returns dict(ok, spread, delta, text). spread/delta are positive magnitudes of what the team loses."""
        roster = self.E[self.E.kp == team]
        names = list(roster.name)
        m = match_name(player, names)
        prev = [match_name(p, names) for p in self.outs.get(team, [])]
        prev = {p for p in prev if p and p != m}
        keep = roster[~roster.name.isin(prev)]
        stand_in = ''
        if m is None:
            tvr = self.TV[(self.TV.team == team)]
            tm = match_name(player, list(tvr.player))
            if tm is None or pd.isna(tvr[tvr.player == tm].gbpm.iloc[0]):
                return dict(ok=False, spread=0.0, delta=0.0, text=f'not in EvanMiya or Torvik files for {team}; not priced')
            bpr = float(tvr[tvr.player == tm].gbpm.iloc[0]); stand_in = ' (Torvik gBPM stand-in; not in EvanMiya file)'
            v = team_value(list(keep.bpr) + [bpr]) - team_value(list(keep.bpr))
            rank = int((roster.bpr > bpr).sum()) + 1; em_counts, em_txt = False, 'EM never rated him'
        else:
            bpr = float(roster[roster.name == m].bpr.iloc[0]); rank = int((roster.bpr > bpr).sum()) + 1
            v = team_value(list(keep.bpr)) - team_value(list(keep[keep.name != m].bpr))
            r0 = self.O20[self.O20.kp == team]; m0 = match_name(player, list(r0.name))
            if m0 is not None and team in self.P.index:
                with_ = self.b1 * team_value(list(r0.bpr)) + self.b0
                wo = self.b1 * team_value(list(r0[r0.name != m0].bpr)) + self.b0
                em_counts = abs(self.P.bpr[team] - with_) <= abs(self.P.bpr[team] - wo)
                em_txt = f'EM {"counts" if em_counts else "removed"}'
            else:
                em_counts, em_txt = False, 'EM: not in Oct 20 file -> removed'
        tvr = self.TV[self.TV.team == team]; tm = match_name(player, list(tvr.player))
        tv_counts = tm is not None and float(tvr[tvr.player == tm].min_pct.iloc[0]) > 0
        share = 0.45 * em_counts + 0.35 + 0.20 * tv_counts
        N = int(self.R.n_games[team]) if team in self.R.index and pd.notna(self.R.n_games[team]) else 0
        lam = N / (N + 8) if N else 0.0
        tb = self.box[(self.box.team_kp == team) & self.box.d1.astype(bool)]
        bm = match_name(player, list(tb.name.unique()))
        played = tb[(tb.name == bm) & (tb.minutes > 0)].gameId.nunique() if bm else 0
        miss = max(N - played, 0) / N if N else 0.0
        adj = share * (1 - lam * miss) * w
        sp = v / 10.35 * 9.5 * adj; dp = v / 10.35 * self.SD * adj
        txt = (f'BPR {bpr:.2f} (#{rank}){stand_in}, value {v / 10.35 * 9.5:.2f} spread full; {em_txt}, Torvik {"counts" if tv_counts else "no"} '
               f'-> unpriced {share:.2f}; played {played} of {N} D-I games, lam {lam:.2f} -> {sp:.2f} spread')
        if register: self.outs.setdefault(team, []).append(player)
        return dict(ok=True, spread=sp, delta=dp, text=txt, cascade=sorted(prev))
