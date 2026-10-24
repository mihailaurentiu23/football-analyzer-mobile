"""Football Analyzer Mobile: personal ESPN-backed analytics PWA.

Standalone backend (separate from Fedora JavaFX); persistent SQLite via DATA_DIR.
Only analyses games: no bookmaker integration, gambling, or real-money features.
Data from unofficial public ESPN endpoints: may be unavailable or restricted.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import math
import os
import re
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('DATA_DIR', str(ROOT / 'data')))
DB_FILE = DATA_DIR / 'football_analyzer.db'
LEAGUES = {
    'eng.1': 'Premier League', 'esp.1': 'La Liga', 'ita.1': 'Serie A',
    'ger.1': 'Bundesliga', 'fra.1': 'Ligue 1'
}
API = 'https://site.api.espn.com/apis/site/v2/sports/soccer/'
TZ = ZoneInfo('Europe/Bucharest')
METRICS = {
    'GOALS': 'Goluri', 'CORNERS': 'Cornere', 'SHOTS_ON_TARGET': 'Șuturi pe poartă',
    'SHOTS': 'Șuturi totale', 'OFFSIDES': 'Ofsaiduri', 'SAVES': 'Intervenții portar',
    'FOULS': 'Faulturi', 'YELLOW': 'Cartonașe galbene', 'RED': 'Cartonașe roșii',
}
KEY_ALIASES = {
    'woncorners':'CORNERS','cornerkicks':'CORNERS','corners':'CORNERS','cornerswon':'CORNERS','totalcorners':'CORNERS','ck':'CORNERS',
    'shotsontarget':'SHOTS_ON_TARGET','shotsongoal':'SHOTS_ON_TARGET','shotsonnet':'SHOTS_ON_TARGET','shotson':'SHOTS_ON_TARGET','sot':'SHOTS_ON_TARGET','totalshotsongoal':'SHOTS_ON_TARGET','ontargetscoringattempts':'SHOTS_ON_TARGET',
    'totalshots':'SHOTS','shots':'SHOTS','shotstotal':'SHOTS','shotattempts':'SHOTS','totalshotattempts':'SHOTS',
    'foulscommitted':'FOULS','fouls':'FOULS','totalfouls':'FOULS',
    'offsides':'OFFSIDES','offside':'OFFSIDES',
    'saves':'SAVES','goalkeepersaves':'SAVES','savesmade':'SAVES',
    'yellowcards':'YELLOW','yellowcard':'YELLOW','yc':'YELLOW',
    'redcards':'RED','redcard':'RED','rc':'RED',
}
PLAYER_ALIASES = {
    'goals':'GOALS', 'assists':'ASSISTS', 'shots':'SHOTS', 'totalshots':'SHOTS',
    'shotsontarget':'SHOTS_ON_TARGET', 'shotsongoal':'SHOTS_ON_TARGET',
    'foulscommitted':'FOULS', 'fouls':'FOULS', 'yellowcards':'YELLOW', 'redcards':'RED',
}
PLAYER_LABELS = {'GOALS':'Goluri', 'ASSISTS':'Pase decisive', 'SHOTS':'Șuturi',
                 'SHOTS_ON_TARGET':'Șuturi pe poartă', 'FOULS':'Faulturi',
                 'YELLOW':'Cartonașe galbene', 'RED':'Cartonașe roșii'}


def norm(value: Any) -> str:
    return re.sub('[^a-z0-9]', '', unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower())


def to_int(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get('value', value.get('displayValue'))
    if isinstance(value, bool):
        return None
    try:
        numeric = float(str(value).replace(',', '.'))
        return int(numeric) if math.isfinite(numeric) and numeric >= 0 and numeric.is_integer() else None
    except (TypeError, ValueError):
        return None


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_time(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(dt.timezone.utc)
    except (AttributeError, ValueError):
        return None


def connect():
    db = sqlite3.connect(DB_FILE, timeout=15, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=15000')
    db.execute('PRAGMA journal_mode=WAL')
    return db


def initialize():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript((ROOT / 'schema-desktop.sql').read_text(encoding='utf-8'))
        db.executescript('''
            CREATE TABLE IF NOT EXISTS prediction_snapshots(
                league TEXT NOT NULL,event_id TEXT NOT NULL,captured_at TEXT NOT NULL,
                kickoff TEXT NOT NULL,sample_size INTEGER NOT NULL,model_version TEXT NOT NULL,
                PRIMARY KEY(league,event_id));
            CREATE TABLE IF NOT EXISTS prediction_markets(
                league TEXT NOT NULL,event_id TEXT NOT NULL,scope TEXT NOT NULL,
                team_id TEXT NOT NULL DEFAULT '', subject_id TEXT NOT NULL DEFAULT '',
                subject_name TEXT NOT NULL DEFAULT '',metric TEXT NOT NULL,kind TEXT NOT NULL,
                threshold INTEGER NOT NULL DEFAULT 0,probability REAL NOT NULL,
                expected REAL,observations INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(league,event_id,scope,team_id,subject_id,metric,kind,threshold));
            CREATE TABLE IF NOT EXISTS mobile_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_mobile_recent ON fixtures(kickoff DESC);
        ''')
        for slug,title in LEAGUES.items():
            db.execute('INSERT OR IGNORE INTO leagues(slug,title) VALUES(?,?)', (slug,title))


def get_meta(key: str) -> str | None:
    with connect() as db:
        row = db.execute('SELECT value FROM mobile_meta WHERE key=?', (key,)).fetchone()
    return row['value'] if row else None


def set_meta(key: str, value: str):
    with connect() as db:
        db.execute('INSERT INTO mobile_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key,value))


def scoreboard_matches(payload: dict, league: str) -> list[dict]:
    result = []
    for event in payload.get('events', []):
        comps = event.get('competitions') or []
        if not comps: continue
        comp = comps[0]
        comp_status = comp.get('status') or {}
        state = (event.get('status') or comp_status).get('type') or {}
        date = parse_time(event.get('date') or comp.get('date'))
        if not date: continue
        sides = {c.get('homeAway'): c for c in comp.get('competitors', [])}
        if 'home' not in sides or 'away' not in sides: continue
        home,away = sides['home'],sides['away']
        hteam,ateam = home.get('team') or {}, away.get('team') or {}
        if not hteam.get('id') or not ateam.get('id'): continue
        completed = bool(state.get('completed') or (event.get('status') or {}).get('completed') or state.get('state') == 'post')
        scheduled = not completed and (state.get('state') == 'pre' or date > utc_now())
        if not scheduled and not completed: continue
        result.append(dict(league=league,event_id=str(event['id']),kickoff=date.isoformat(),
           home_id=str(hteam['id']),home_name=hteam.get('displayName') or hteam.get('shortDisplayName') or hteam.get('name') or '',
           away_id=str(ateam['id']),away_name=ateam.get('displayName') or ateam.get('shortDisplayName') or ateam.get('name') or '',
           completed=int(completed),scheduled=int(scheduled),home_goals=to_int(home.get('score')) if completed else None,
           away_goals=to_int(away.get('score')) if completed else None))
    return result


def save_fixtures(matches: list[dict]):
    with connect() as db:
        for m in matches:
            db.execute('''INSERT INTO fixtures(league,event_id,kickoff,home_id,home_name,away_id,away_name,completed,scheduled,home_goals,away_goals,modified_at)
                VALUES(:league,:event_id,:kickoff,:home_id,:home_name,:away_id,:away_name,:completed,:scheduled,:home_goals,:away_goals,:now)
                ON CONFLICT(league,event_id) DO UPDATE SET kickoff=excluded.kickoff, home_id=excluded.home_id,
                away_id=excluded.away_id,home_name=excluded.home_name,away_name=excluded.away_name,
                completed=excluded.completed,scheduled=excluded.scheduled,home_goals=excluded.home_goals,
                away_goals=excluded.away_goals,modified_at=excluded.modified_at''', dict(m,now=utc_now().isoformat()))


def match_by_id(league: str,event_id: str) -> dict | None:
    with connect() as db:
        r=db.execute('SELECT * FROM fixtures WHERE league=? AND event_id=?',(league,event_id)).fetchone()
    return dict(r) if r else None


def source_team_stats(payload: dict, fixture: dict) -> dict[tuple[str,str],int]:
    vals = {}
    for path in [((payload.get('header') or {}).get('competitions') or []), payload.get('competitions') or []]:
        if path:
            for e in path[0].get('competitors',[]):
                add_team_stats(vals,e,fixture)
    for e in ((payload.get('boxscore') or {}).get('teams') or []):
        add_team_stats(vals,e,fixture)
    return vals


def add_team_stats(out:dict,entry:dict, fixture:dict):
    tid=str((entry.get('team') or {}).get('id') or entry.get('teamId') or '')
    if tid == fixture['home_id']: side='home'
    elif tid == fixture['away_id']: side='away'
    elif not tid and entry.get('homeAway') in ('home','away'):side=entry['homeAway']
    else:return
    for s in (entry.get('statistics') or entry.get('stats') or []):
        key=KEY_ALIASES.get(norm(s.get('name') or s.get('type') or s.get('key') or s.get('abbreviation') or s.get('label')))
        if key:
            n=to_int(s.get('value'))
            if n is None:n=to_int(s.get('displayValue'))
            if n is not None:out[(side,key)]=n


def is_keeper(pos: str) -> bool:
    x=norm(pos)
    return x in {'g','gk','goalkeeper'}


def extract_rosters(payload:dict, fixture:dict):
    output={}
    for group in payload.get('rosters') or []:
        tid=str((group.get('team') or {}).get('id') or group.get('teamId') or '')
        if not tid and group.get('homeAway') in ('home','away'):
            tid=fixture[group['homeAway']+'_id']
        if tid not in (fixture['home_id'],fixture['away_id']):continue
        team_name=fixture['home_name'] if tid==fixture['home_id'] else fixture['away_name']
        entries=[]
        for item in group.get('roster') or group.get('athletes') or []:
            athlete=item.get('athlete') or item
            pname=athlete.get('displayName') or athlete.get('fullName') or athlete.get('name')
            if not pname:continue
            pid=str(athlete.get('id') or 'name:'+norm(pname))
            p=item.get('position') or athlete.get('position') or {}
            position=p.get('abbreviation') or p.get('name') or '' if isinstance(p,dict) else str(p)
            formation_place=to_int(item.get('formationPlace')) or 0
            starter=bool(item.get('starter'))
            stats={}
            for s in item.get('stats') or item.get('statistics') or []:
                key=PLAYER_ALIASES.get(norm(s.get('name') or s.get('type') or s.get('abbreviation') or s.get('label')))
                n=to_int(s.get('value'))
                if n is None: n=to_int(s.get('displayValue'))
                if key and n is not None:stats[key]=n
            appeared=starter or bool(item.get('subbedIn')) or (not item.get('didNotPlay') and bool(stats))
            if not appeared:continue
            entries.append(dict(player_id=pid,name=pname,team_id=tid,team_name=team_name,
                jersey=str(item.get('jersey') or athlete.get('jersey') or ''),position=position,
                starter=int(starter),played=int(appeared),formation_place=formation_place,stats=stats))
        output[tid]=dict(formation=str(group.get('formation') or ''),players=entries)
    return output


def save_summary(fixture:dict,payload:dict):
    stats=source_team_stats(payload,fixture)
    # A complete game with only placeholder zero stats is not a verified stats report.
    has_activity=any(v>0 for (_,metric),v in stats.items() if metric not in ('YELLOW','RED','OFFSIDES'))
    rosters=extract_rosters(payload,fixture)
    with connect() as db:
        # Don't overwrite useful previous stats with empty responses.
        # Merge provider fields. A later partial ESPN report must not erase valid cached stats.
        # Values explicitly received may replace their own old value, never unrelated metrics.
        if fixture['completed'] and not has_activity:
            # A zero-only ESPN payload may be a placeholder. Do not store unsupported zeros.
            stats={k:v for k,v in stats.items() if v>0}
        for (side,metric),value in stats.items():
            db.execute('''INSERT INTO team_stats(league,event_id,side,metric,value) VALUES(?,?,?,?,?)
                ON CONFLICT(league,event_id,side,metric) DO UPDATE SET value=excluded.value''',
                (fixture['league'],fixture['event_id'],side,metric,value))
        for tid,group in rosters.items():
            if group['formation']:
                db.execute('''INSERT INTO lineups(league,event_id,team_id,formation) VALUES(?,?,?,?)
                    ON CONFLICT(league,event_id,team_id) DO UPDATE SET formation=excluded.formation''',
                    (fixture['league'],fixture['event_id'],tid,group['formation']))
            starters=[p for p in group['players'] if p['starter']]
            # Only a complete actual eleven is trusted as a confirmed XI.
            if len(starters)==11 and len({p['player_id'] for p in starters})==11 and sum(is_keeper(p['position']) or p['formation_place']==1 for p in starters)==1:
                db.execute('DELETE FROM player_appearances WHERE league=? AND event_id=? AND team_id=?',
                          (fixture['league'],fixture['event_id'],tid))
                db.execute('DELETE FROM player_stats WHERE league=? AND event_id=? AND team_id=?',
                          (fixture['league'],fixture['event_id'],tid))
            for p in group['players']:
                db.execute('''INSERT INTO player_appearances(league,event_id,team_id,player_id,name,team_name,jersey,position,starter,played,formation_place)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(league,event_id,team_id,player_id) DO UPDATE SET
                  name=excluded.name,team_name=excluded.team_name,jersey=excluded.jersey,
                  position=excluded.position,starter=excluded.starter,played=excluded.played,formation_place=excluded.formation_place''',
                    (fixture['league'],fixture['event_id'],tid,p['player_id'],p['name'],p['team_name'],p['jersey'],
                     p['position'],p['starter'],p['played'],p['formation_place']))
                for metric,value in p['stats'].items():
                    db.execute('''INSERT INTO player_stats(league,event_id,team_id,player_id,metric,value) VALUES(?,?,?,?,?,?)
                        ON CONFLICT(league,event_id,team_id,player_id,metric) DO UPDATE SET value=excluded.value''',
                        (fixture['league'],fixture['event_id'],tid,p['player_id'],metric,value))
        db.execute('''INSERT INTO summary_sync(league,event_id,checked_at,has_team_stats,has_player_stats)
            VALUES(?,?,?,?,?) ON CONFLICT(league,event_id) DO UPDATE SET
            checked_at=excluded.checked_at,has_team_stats=excluded.has_team_stats,
            has_player_stats=excluded.has_player_stats''',
            (fixture['league'],fixture['event_id'],utc_now().isoformat(),int(bool(stats)),int(bool(rosters))))


def read_fixture_list(scope:str='upcoming',league:str='',query:str='',limit:int=70):
    clauses=[];args=[]
    if scope=='upcoming':clauses.append('kickoff >= ? AND completed=0');args.append((utc_now()-dt.timedelta(minutes=20)).isoformat())
    elif scope=='finished':clauses.append('completed=1');
    else:raise ValueError('Invalid scope')
    if league in LEAGUES:clauses.append('league=?');args.append(league)
    where=' WHERE '+' AND '.join(clauses) if clauses else ''
    ordering='ASC' if scope=='upcoming' else 'DESC'
    # Query filter in Python for normalization/accents.
    with connect() as db:
        rows=db.execute(f'SELECT * FROM fixtures{where} ORDER BY kickoff {ordering} LIMIT 550',args).fetchall()
    items=[dict(r) for r in rows]
    if query:items=[m for m in items if norm(query) in norm(m['home_name']+' '+m['away_name'])]
    return items[:limit]


def fixture_stats(fixture:dict):
    with connect() as db:
        rows=db.execute('SELECT side,metric,value FROM team_stats WHERE league=? AND event_id=?',
                       (fixture['league'],fixture['event_id'])).fetchall()
    stats={'home':{},'away':{},'total':{}}
    if fixture['home_goals'] is not None:stats['home']['GOALS']=fixture['home_goals']
    if fixture['away_goals'] is not None:stats['away']['GOALS']=fixture['away_goals']
    for r in rows:stats[r['side']][r['metric']]=r['value']
    for metric in METRICS:
        if metric in stats['home'] and metric in stats['away']:
            stats['total'][metric]=stats['home'][metric]+stats['away'][metric]
    return stats


def player_search(query:str='',limit:int=30):
    with connect() as db:
        rows=db.execute('''SELECT a.league,a.team_id,a.player_id,a.name,a.team_name,a.jersey,a.position,max(f.kickoff) last_seen
            FROM player_appearances a JOIN fixtures f ON a.league=f.league AND a.event_id=f.event_id
            GROUP BY a.league,a.team_id,a.player_id ORDER BY last_seen DESC LIMIT 2500''').fetchall()
    q=norm(query)
    items=[dict(r) for r in rows if not q or q in norm(r['name']) or q in norm(r['team_name'])]
    return items[:limit]


def player_profile(league:str,team_id:str,player_id:str):
    with connect() as db:
        rows=db.execute('''SELECT a.*,f.kickoff,f.home_name,f.away_name,f.home_id,f.away_id,s.metric,s.value
            FROM player_appearances a JOIN fixtures f ON f.league=a.league AND f.event_id=a.event_id
            LEFT JOIN player_stats s ON s.league=a.league AND s.event_id=a.event_id
               AND s.team_id=a.team_id AND s.player_id=a.player_id
            WHERE a.league=? AND a.team_id=? AND a.player_id=?
              AND f.completed=1 AND f.kickoff<? AND a.played=1
            ORDER BY f.kickoff DESC LIMIT 750''',
            (league,team_id,player_id,utc_now().isoformat())).fetchall()
    if not rows:return None
    games={}
    for r in rows:
        eid=r['event_id']
        if eid not in games:
            games[eid]={'event_id':eid,'kickoff':r['kickoff'],'opponent':r['away_name'] if team_id==r['home_id'] else r['home_name'],
                        'starter':bool(r['starter']),'stats':{}}
        if r['metric']:games[eid]['stats'][r['metric']]=r['value']
    recent=list(games.values())[:15]
    averages={}
    for metric,label in PLAYER_LABELS.items():
        vals=[g['stats'][metric] for g in recent if metric in g['stats']]
        if len(vals)>=3:
            weights=[0.86**i for i,g in enumerate(recent) if metric in g['stats']]
            mean=sum(v*w for v,w in zip(vals,weights))/sum(weights)
            averages[metric]={'label':label,'value':round(mean,2),'samples':len(vals)}
    first=rows[0]
    return dict(name=first['name'],team=first['team_name'],jersey=first['jersey'],position=first['position'],
                league=league,player_id=player_id,games=recent,averages=averages)


def weighted_avg(observations:list[dict],metric:str,own:bool,venue:bool|None):
    total=weights=0.0
    for i,ob in enumerate(observations):
        if venue is not None and ob['home']!=venue:continue
        value=(ob['own'] if own else ob['against']).get(metric)
        if value is None:continue
        weight=0.86**i
        total+=weight*value;weights+=weight
    return total/weights if weights else None


def adjusted_avg(observations:list[dict],metric:str,own:bool,home:bool):
    overall=weighted_avg(observations,metric,own,None)
    at_venue=weighted_avg(observations,metric,own,home)
    if overall is None:return None
    if at_venue is None:return overall
    count=sum(ob['home']==home and (ob['own'] if own else ob['against']).get(metric) is not None for ob in observations)
    factor=0.65 if count>=3 else 0.5 if count==2 else 0.25
    return factor*at_venue+(1-factor)*overall


def poisson_atleast(lam:float,k:int)->float:
    if k<=0:return 1.0
    p=math.exp(-max(0,lam));less=p
    for i in range(1,k):
        p*=lam/i
        less+=p
    return max(0.0,min(1.0,1-less))


def forecast_for(fixture:dict, n:int=10):
    # Strict cut-off: historical observations before kickoff and current time.
    cutoff=min(parse_time(fixture['kickoff']) or utc_now(),utc_now()).isoformat()
    with connect() as db:
        rows=db.execute('''SELECT * FROM fixtures WHERE league=? AND completed=1 AND kickoff<?
            AND (home_id IN (?,?) OR away_id IN (?,?)) ORDER BY kickoff DESC LIMIT 400''',
            (fixture['league'],cutoff,fixture['home_id'],fixture['away_id'],fixture['home_id'],fixture['away_id'])).fetchall()
        matches=[dict(x) for x in rows]
        observations={}
        for side in ('home','away'):
            tid=fixture[side+'_id']
            team_matches=[m for m in matches if m['home_id']==tid or m['away_id']==tid][:n]
            gathered=[]
            for m in team_matches:
                h=m['home_id']==tid
                s=db.execute('SELECT side,metric,value FROM team_stats WHERE league=? AND event_id=?',
                             (m['league'],m['event_id'])).fetchall()
                game={'home':h,'own':{},'against':{}}
                if m['home_goals'] is not None and m['away_goals'] is not None:
                    game['own']['GOALS']=m['home_goals'] if h else m['away_goals']
                    game['against']['GOALS']=m['away_goals'] if h else m['home_goals']
                for row in s:
                    (game['own'] if row['side']==('home' if h else 'away') else game['against'])[row['metric']]=row['value']
                gathered.append(game)
            observations[side]=gathered
    estimates={}
    for metric,label in METRICS.items():
        hh=observations['home'];aa=observations['away']
        home_n=sum(metric in o['own'] and metric in o['against'] for o in hh)
        away_n=sum(metric in o['own'] and metric in o['against'] for o in aa)
        if min(home_n,away_n)<3:continue
        ha=adjusted_avg(hh,metric,True,True)
        ad=adjusted_avg(aa,metric,False,False)
        aa_=adjusted_avg(aa,metric,True,False)
        hd=adjusted_avg(hh,metric,False,True)
        if any(x is None for x in (ha,ad,aa_,hd)):continue
        cap=6 if metric=='GOALS' else 35 if metric=='FOULS' else 32
        home=min(cap,max(0,(ha+ad)/2));away=min(cap,max(0,(aa_+hd)/2))
        estimates[metric]={'label':label,'home':round(home,3),'away':round(away,3),
                           'total':round(home+away,3),'samples_home':home_n,'samples_away':away_n}
    return estimates


def thresholds(metric:str,scope:str):
    if scope=='total':
        return {'GOALS':7,'CORNERS':17,'SHOTS_ON_TARGET':17,'SHOTS':39,'OFFSIDES':9,'SAVES':13,
                'FOULS':41,'YELLOW':9,'RED':4}.get(metric,7)
    return {'GOALS':7,'CORNERS':17,'SHOTS_ON_TARGET':14,'SHOTS':31,'OFFSIDES':10,'SAVES':15,
            'FOULS':36,'YELLOW':10,'RED':5}.get(metric,7)


def probabilities(estimates:dict):
    output={}
    for metric,item in estimates.items():
        tabs={}
        for scope in ('total','home','away'):
            lam=item[scope]
            levels=range(1,thresholds(metric,scope)+1)
            tabs[scope]=[{'threshold':k-.5,'over':round(100*poisson_atleast(lam,k),1),
                           'under':round(100*(1-poisson_atleast(lam,k)),1)} for k in levels]
        output[metric]=dict(item,levels=tabs)
    return output


def save_forecast_before_kickoff(fixture:dict,forecast:dict):
    if not forecast or fixture['completed'] or not fixture['scheduled'] or parse_time(fixture['kickoff'])<=utc_now():
        return
    with connect() as db:
        exists=db.execute('SELECT 1 FROM prediction_snapshots WHERE league=? AND event_id=?',
                         (fixture['league'],fixture['event_id'])).fetchone()
        if exists:return
        now=utc_now().isoformat()
        db.execute('''INSERT INTO prediction_snapshots(league,event_id,captured_at,kickoff,sample_size,model_version)
            VALUES(?,?,?,?,?,?)''',(fixture['league'],fixture['event_id'],now,fixture['kickoff'],10,'mobile-1.0'))
        for metric,entry in forecast.items():
            for scope in ('total','home','away'):
                sc='TEAM' if scope=='total' else scope.upper()
                team_id='' if scope=='total' else fixture[scope+'_id']
                subject='' if scope=='total' else fixture[scope+'_name']
                expected=entry[scope]
                samples=min(entry['samples_home'],entry['samples_away']) if scope=='total' else entry['samples_'+scope]
                for item in entry['levels'][scope]:
                    k=int(item['threshold']+.5)
                    for kind,prob in (('OVER',item['over']),('UNDER',item['under'])):
                        db.execute('''INSERT INTO prediction_markets(league,event_id,scope,team_id,subject_id,subject_name,
                            metric,kind,threshold,probability,expected,observations) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (fixture['league'],fixture['event_id'],sc,team_id,'',subject,metric,kind,k,prob/100,expected,samples))


def archived_evaluation(fixture:dict):
    stats=fixture_stats(fixture)
    with connect() as db:
        snapshot=db.execute('SELECT * FROM prediction_snapshots WHERE league=? AND event_id=?',
                            (fixture['league'],fixture['event_id'])).fetchone()
        if not snapshot:return dict(saved=False,entries=[],summary=None)
        rows=db.execute('''SELECT * FROM prediction_markets WHERE league=? AND event_id=?
             AND kind IN ('OVER','UNDER') ORDER BY scope,metric,kind,threshold LIMIT 1200''',
            (fixture['league'],fixture['event_id'])).fetchall()
    entries=[];brier=[]
    for r in rows:
        scope='total' if r['scope']=='TEAM' else r['scope'].lower()
        observed=stats.get(scope,{}).get(r['metric'])
        happened=None if observed is None else (observed>=r['threshold'] if r['kind']=='OVER' else observed<r['threshold'])
        if happened is not None:
            brier.append((r['probability']-(1 if happened else 0))**2)
        entries.append(dict(scope=scope,metric=r['metric'],kind=r['kind'],threshold=r['threshold']-.5,
                            predicted=round(100*r['probability'],1),actual=observed,happened=happened))
    return dict(saved=True,captured_at=snapshot['captured_at'],entries=entries,
                summary=dict(evaluated=len(brier),unavailable=len(entries)-len(brier),
                             brier=round(sum(brier)/len(brier),4) if brier else None))


async def fetch_espn(url:str) -> dict:
    async with httpx.AsyncClient(timeout=18,follow_redirects=False,headers={
        'User-Agent':'FootballAnalyzerMobile/1.0 (personal project)', 'Accept':'application/json'}) as client:
        r=await client.get(url)
        r.raise_for_status()
        if 'json' not in r.headers.get('content-type','').lower():
            raise ValueError('ESPN nu a returnat JSON')
        return r.json()


sync_lock=threading.Lock()
sync_state={'running':False,'message':'Inițializare','errors':[], 'updated_at':None}
async def run_sync():
    if not sync_lock.acquire(blocking=False):return
    sync_state.update(running=True,message='Actualizez meciurile din ESPN',errors=[])
    received=0
    try:
        today=dt.datetime.now(TZ).date()
        start=dt.date(today.year if today.month>=7 else today.year-1,7,1)
        end=today+dt.timedelta(days=35)
        months=[];current=dt.date(start.year,start.month,1)
        while current<=end:
            months.append(current.strftime('%Y%m'))
            current=dt.date(current.year+int(current.month==12),(current.month % 12)+1,1)
        sem=asyncio.Semaphore(4)
        async def one(league,month):
            async with sem:
                url=API+league+'/scoreboard?dates='+month+'&limit=200'
                try:
                    payload=await fetch_espn(url)
                    return scoreboard_matches(payload,league),None
                except Exception as e:
                    return [],f'{LEAGUES[league]} {month}: {str(e)[:110]}'
        for league in LEAGUES:
            for batch_index in range(0,len(months),3):
                parts=await asyncio.gather(*(one(league,month) for month in months[batch_index:batch_index+3]))
                for games,error in parts:
                    if games:save_fixtures(games);received+=len(games)
                    if error:sync_state['errors'].append(error)
        # Freeze predictions for future fixtures only; no retroactive estimates.
        upcoming=read_fixture_list('upcoming',limit=100)
        for m in upcoming:
            try:
                est=forecast_for(m)
                if est:save_forecast_before_kickoff(m,probabilities(est))
            except Exception:pass
        sync_state['message']=f'S-au citit {received} înregistrări ESPN'
        sync_state['updated_at']=utc_now().isoformat()
        set_meta('last_refresh',sync_state['updated_at'])
    except Exception as e:
        sync_state['errors'].append(str(e)[:250])
        sync_state['message']='Actualizarea ESPN a eșuat'
    finally:
        sync_state['running']=False
        sync_lock.release()


async def fetch_summary_if_needed(fixture:dict, force:bool=False):
    with connect() as db:
        row=db.execute('SELECT checked_at,has_team_stats,has_player_stats FROM summary_sync WHERE league=? AND event_id=?',
                       (fixture['league'],fixture['event_id'])).fetchone()
    cutoff=dt.timedelta(hours=12 if fixture['completed'] else 0,minutes=10 if not fixture['completed'] else 0)
    if row and not force:
        checked=parse_time(row['checked_at'])
        if checked and utc_now()-checked<cutoff and (row['has_team_stats'] or row['has_player_stats']):return
    payload=await fetch_espn(API+fixture['league']+'/summary?event='+fixture['event_id'])
    save_summary(fixture,payload)


async def prepare_game_details(fixture:dict, max_games:int=10):
    # Fetch detailed stats for each side's 10 latest finished fixtures, only on request.
    cutoff=min(parse_time(fixture['kickoff']) or utc_now(),utc_now()).isoformat()
    with connect() as db:
        rows=db.execute('''SELECT * FROM fixtures WHERE league=? AND completed=1 AND kickoff<?
          AND (home_id IN (?,?) OR away_id IN (?,?)) ORDER BY kickoff DESC LIMIT 350''',
            (fixture['league'],cutoff,fixture['home_id'],fixture['away_id'],fixture['home_id'],fixture['away_id'])).fetchall()
    seen=set();selected=[]
    for side in ('home','away'):
        tid=fixture[side+'_id'];count=0
        for row in rows:
            m=dict(row);mid=m['event_id']
            if (m['home_id']==tid or m['away_id']==tid) and mid not in seen:
                seen.add(mid);selected.append(m);count+=1
            elif (m['home_id']==tid or m['away_id']==tid):count+=1
            if count>=max_games:break
    sem=asyncio.Semaphore(4)
    async def one(m):
        async with sem:
            try:await fetch_summary_if_needed(m)
            except Exception:pass
    await asyncio.gather(*(one(m) for m in selected))


async def periodic_loop():
    while True:
        await asyncio.sleep(60*45)
        try:await run_sync()
        except Exception:pass


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize()
    task=asyncio.create_task(periodic_loop())
    # Fetch on server startup if the last sync is old.
    previous=parse_time(get_meta('last_refresh') or '')
    first=asyncio.create_task(run_sync()) if not previous or utc_now()-previous>dt.timedelta(minutes=45) else None
    yield
    for pending in [task,first]:
        if pending:
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):await pending

app=FastAPI(title='Football Analyzer Mobile',version='1.0',lifespan=lifespan,
            docs_url=None,redoc_url=None)
STATIC=ROOT/'static'
app.mount('/static',StaticFiles(directory=str(STATIC)),name='static')


def guard(request:Request):
    expected=os.environ.get('APP_ACCESS_TOKEN','').strip()
    if expected and request.headers.get('X-FA-Token','')!=expected:
        raise HTTPException(status_code=401,detail='Cod de acces necesar')

@app.get('/')
def index():return FileResponse(STATIC/'index.html',headers={'Cache-Control':'no-cache'})

@app.get('/manifest.webmanifest')
def manifest():return FileResponse(STATIC/'manifest.webmanifest',media_type='application/manifest+json')

@app.get('/sw.js')
def sw():return FileResponse(STATIC/'sw.js',media_type='application/javascript',headers={'Service-Worker-Allowed':'/'})

@app.get('/api/status',dependencies=[Depends(guard)])
def status():
    with connect() as db:
        count=db.execute('SELECT count(*) FROM fixtures').fetchone()[0]
        players=db.execute('SELECT count(distinct player_id) FROM player_appearances').fetchone()[0]
    return dict(**sync_state,last_refresh=get_meta('last_refresh'),fixtures=count,players=players,
                persistent_data_required=True)

@app.get('/api/fixtures',dependencies=[Depends(guard)])
def fixtures(scope:str='upcoming',league:str='',q:str=''):
    if scope not in ('upcoming','finished'):raise HTTPException(400,'Tip de listă necunoscut')
    return {'fixtures':read_fixture_list(scope,league,q,limit=120),'leagues':LEAGUES}

@app.get('/api/match/{league}/{event_id}',dependencies=[Depends(guard)])
async def match_details(league:str,event_id:str):
    fixture=match_by_id(league,event_id)
    if not fixture:raise HTTPException(404,'Meci indisponibil')
    if not fixture['completed']:
        await prepare_game_details(fixture)
    est=probabilities(forecast_for(fixture)) if not fixture['completed'] else {}
    if est:save_forecast_before_kickoff(fixture,est)
    return {'fixture':fixture,'estimates':est,'statistics':fixture_stats(fixture),
            'archive':archived_evaluation(fixture) if fixture['completed'] else None,
            'leagues':LEAGUES}

@app.get('/api/match/{league}/{event_id}/lineups',dependencies=[Depends(guard)])
async def lineups(league:str,event_id:str):
    fixture=match_by_id(league,event_id)
    if not fixture:raise HTTPException(404,'Meci indisponibil')
    try:await fetch_summary_if_needed(fixture)
    except Exception:pass
    result={}
    with connect() as db:
        for side in ('home','away'):
            tid=fixture[side+'_id']
            rows=db.execute('''SELECT * FROM player_appearances WHERE league=? AND event_id=? AND team_id=? AND starter=1''',
                            (league,event_id,tid)).fetchall()
            formation=db.execute('SELECT formation FROM lineups WHERE league=? AND event_id=? AND team_id=?',
                                 (league,event_id,tid)).fetchone()
            confirmed=len(rows)==11 and sum(is_keeper(r['position']) or r['formation_place']==1 for r in rows)==1
            source='XI confirmat ESPN' if confirmed else 'Ultimul XI verificat (nu este o predicție)'
            if not confirmed:
                candidates=db.execute('''SELECT a.event_id,max(f.kickoff) kickoff FROM player_appearances a
                  JOIN fixtures f ON a.league=f.league AND a.event_id=f.event_id
                  WHERE a.league=? AND a.team_id=? AND a.starter=1 AND f.completed=1
                    AND f.kickoff<? GROUP BY a.event_id HAVING count(*)=11
                  ORDER BY f.kickoff DESC LIMIT 12''',(league,tid,fixture['kickoff'])).fetchall()
                old=None
                for candidate in candidates:
                    provisional=db.execute('''SELECT * FROM player_appearances WHERE league=? AND event_id=? AND team_id=? AND starter=1''',
                                           (league,candidate['event_id'],tid)).fetchall()
                    if len(provisional)==11 and sum(is_keeper(p['position']) or p['formation_place']==1 for p in provisional)==1:
                        old=candidate;rows=provisional;break
                if old:
                    formation=db.execute('''SELECT formation FROM lineups WHERE league=? AND event_id=? AND team_id=?''',
                                         (league,old['event_id'],tid)).fetchone()
                    source+=' · '+old['kickoff'][:10]
                else:rows=[];source='XI indisponibil'
            ordered=sorted([dict(r) for r in rows],key=lambda x:(x['formation_place'] or 99,x['name']))
            result[side]={'name':fixture[side+'_name'],'team_id':tid,'formation':formation['formation'] if formation else '',
                          'confirmed':confirmed,'source':source,'players':ordered}
    return result

@app.get('/api/players',dependencies=[Depends(guard)])
def players(q:str=''):
    return {'players':player_search(q)}

@app.get('/api/player/{league}/{team_id}/{player_id}',dependencies=[Depends(guard)])
def player(league:str,team_id:str,player_id:str):
    profile=player_profile(league,team_id,player_id)
    if not profile:raise HTTPException(404,'Profil fără date')
    return profile

@app.get('/api/history',dependencies=[Depends(guard)])
def history(league:str=''):
    matches=read_fixture_list('finished',league,limit=100)
    return {'fixtures':matches,'leagues':LEAGUES}

@app.post('/api/refresh',dependencies=[Depends(guard)])
async def refresh(background_tasks:BackgroundTasks):
    accepted=not sync_state['running']
    if accepted:
        background_tasks.add_task(run_sync)
    return {'accepted':accepted,'running':True}

@app.post('/api/match/{league}/{event_id}/refresh',dependencies=[Depends(guard)])
async def refresh_game(league:str,event_id:str):
    fixture=match_by_id(league,event_id)
    if not fixture:raise HTTPException(404,'Meci indisponibil')
    await fetch_summary_if_needed(fixture,force=True)
    return {'ok':True,'statistics':fixture_stats(fixture)}
