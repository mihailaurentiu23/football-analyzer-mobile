import asyncio
import datetime as dt
from pathlib import Path
import pytest
import server

@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA_DIR',tmp_path)
    monkeypatch.setattr(server,'DB_FILE',tmp_path/'testing.db')
    server.initialize()
    return tmp_path

def test_scoreboard_and_scores(store):
    end=(server.utc_now()+dt.timedelta(hours=4)).isoformat()
    past=(server.utc_now()-dt.timedelta(days=3)).isoformat()
    payload={'events':[
      {'id':'999','date':end,'status':{'type':{'state':'pre','completed':False}},
       'competitions':[{'competitors':[{'homeAway':'home','team':{'id':'1','displayName':'AC Unirea'}},
                                        {'homeAway':'away','team':{'id':'2','displayName':'CS Viitorul'}}]}]},
      {'id':'998','date':past,'status':{'type':{'state':'post','completed':True}},
       'competitions':[{'competitors':[{'homeAway':'home','team':{'id':'1','displayName':'AC Unirea'},'score':'2'},
                                        {'homeAway':'away','team':{'id':'2','displayName':'CS Viitorul'},'score':'1'}]}]}
    ]}
    games=server.scoreboard_matches(payload,'eng.1')
    assert len(games)==2
    assert games[1]['completed']==1 and games[1]['home_goals']==2
    server.save_fixtures(games)
    assert len(server.read_fixture_list('upcoming'))==1
    assert len(server.read_fixture_list('finished'))==1

def test_stats_missing_vs_zero(store):
    m={'league':'eng.1','event_id':'33','home_id':'1','away_id':'2',
       'home_name':'Unirea','away_name':'Viitorul','completed':1,'scheduled':0,
       'home_goals':2,'away_goals':1,'kickoff':server.utc_now().isoformat()}
    server.save_fixtures([m])
    empty={'boxscore':{'teams':[{'team':{'id':'1'},'statistics':[{'name':'wonCorners','value':0}]}]}}
    server.save_summary(m,empty)
    stats=server.fixture_stats(m)
    assert stats['home']['GOALS']==2 and stats['away']['GOALS']==1
    assert 'CORNERS' not in stats['total'] and 'CORNERS' not in stats['home']
    good={'boxscore':{'teams':[{'team':{'id':'1'},'statistics':[{'name':'wonCorners','value':4},{'name':'totalShots','value':14}]},
                               {'team':{'id':'2'},'statistics':[{'name':'wonCorners','value':0},{'name':'totalShots','value':10}]}]}}
    server.save_summary(m,good)
    stats=server.fixture_stats(m)
    assert stats['home']['CORNERS']==4 and stats['away']['CORNERS']==0
    assert stats['total']['CORNERS']==4
    assert stats['total']['SHOTS']==24
    # Partial response later must not remove older valid values.
    server.save_summary(m,{'boxscore':{'teams':[{'team':{'id':'1'},'statistics':[{'name':'shotsOnTarget','value':4}]}]}})
    assert server.fixture_stats(m)['total']['CORNERS']==4

def test_poisson_probabilities(store):
    assert abs(server.poisson_atleast(2,1)-(1-__import__('math').exp(-2)))<1e-9
    assert server.poisson_atleast(0,1)==0
    for lam in [0,0.3,1.5,2.8,12.5]:
        for k in range(1,15):
            p=server.poisson_atleast(lam,k)
            assert 0<=p<=1
            assert p==pytest.approx(1-(1-p))
        assert all(server.poisson_atleast(lam,k)>=server.poisson_atleast(lam,k+1) for k in range(1,15))

def test_archive_before_kickoff_only(store):
    m={'league':'eng.1','event_id':'49','home_id':'1','away_id':'2',
       'home_name':'Unirea','away_name':'Viitorul','completed':0,'scheduled':1,
       'home_goals':None,'away_goals':None,'kickoff':(server.utc_now()+dt.timedelta(hours=2)).isoformat()}
    server.save_fixtures([m])
    forecast={'GOALS':{'home':1.5,'away':0.8,'total':2.3,'samples_home':8,'samples_away':9}}
    p=server.probabilities(forecast)
    server.save_forecast_before_kickoff(m,p)
    first=server.archived_evaluation(m)
    assert first['saved']
    server.save_forecast_before_kickoff(m,server.probabilities({'GOALS':dict(forecast['GOALS'],home=5)}))
    assert server.archived_evaluation(m)['captured_at']==first['captured_at']
    # No retroactive creation.
    m2=dict(m,event_id='50',kickoff=(server.utc_now()-dt.timedelta(hours=2)).isoformat(),completed=1,scheduled=0,home_goals=2,away_goals=1)
    server.save_fixtures([m2]);server.save_forecast_before_kickoff(m2,p)
    assert not server.archived_evaluation(m2)['saved']

def test_lineup_parser_has_keeper(store):
    fixture={'league':'ita.1','event_id':'69','home_id':'2','away_id':'3','home_name':'Home','away_name':'Away',
        'completed':0,'scheduled':1,'kickoff':server.utc_now().isoformat()}
    payload={'rosters':[{'team':{'id':'2'},'formation':'4-3-3','roster':[
        {'athlete':{'id':str(i),'displayName':('Goalkeeper' if i==1 else f'Player {i}')},
         'position':{'abbreviation':'GK' if i==1 else 'MF'},'starter':True,'formationPlace':i}
        for i in range(1,12)]}]}
    roster=server.extract_rosters(payload,fixture)['2']['players']
    assert len(roster)==11 and roster[0]['position']=='GK'
    assert roster[0]['formation_place']==1

@pytest.mark.asyncio
async def test_api_http(store,monkeypatch):
    from httpx import ASGITransport,AsyncClient
    async with AsyncClient(transport=ASGITransport(app=server.app),base_url='http://test') as client:
        resp=await client.get('/api/status')
        assert resp.status_code==200 and resp.json()['fixtures']==0
        response=await client.get('/api/fixtures')
        assert response.status_code==200 and response.json()['fixtures']==[]
        assert (await client.get('/')).status_code==200
        assert (await client.get('/manifest.webmanifest')).status_code==200
