PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS leagues (slug TEXT PRIMARY KEY, title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fixtures (
  league TEXT NOT NULL, event_id TEXT NOT NULL, kickoff TEXT NOT NULL,
  home_id TEXT NOT NULL, home_name TEXT NOT NULL,
  away_id TEXT NOT NULL, away_name TEXT NOT NULL,
  completed INTEGER NOT NULL DEFAULT 0, scheduled INTEGER NOT NULL DEFAULT 0,
  home_goals INTEGER, away_goals INTEGER, modified_at TEXT NOT NULL,
  PRIMARY KEY(league,event_id)
);
CREATE INDEX IF NOT EXISTS idx_fixtures_date ON fixtures(kickoff);
CREATE INDEX IF NOT EXISTS idx_fixtures_home ON fixtures(league,home_id,kickoff);
CREATE INDEX IF NOT EXISTS idx_fixtures_away ON fixtures(league,away_id,kickoff);
CREATE TABLE IF NOT EXISTS team_stats (
 league TEXT NOT NULL, event_id TEXT NOT NULL, side TEXT NOT NULL CHECK(side IN ('home','away')),
 metric TEXT NOT NULL, value INTEGER NOT NULL CHECK(value >= 0),
 PRIMARY KEY(league,event_id,side,metric)
);
CREATE TABLE IF NOT EXISTS lineups (
 league TEXT NOT NULL, event_id TEXT NOT NULL, team_id TEXT NOT NULL, formation TEXT,
 PRIMARY KEY(league,event_id,team_id)
);
CREATE TABLE IF NOT EXISTS player_appearances (
 league TEXT NOT NULL, event_id TEXT NOT NULL, team_id TEXT NOT NULL, player_id TEXT NOT NULL,
 name TEXT NOT NULL, team_name TEXT NOT NULL, jersey TEXT, position TEXT,
 starter INTEGER NOT NULL DEFAULT 0, played INTEGER NOT NULL DEFAULT 1,
 formation_place INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(league,event_id,team_id,player_id)
);
CREATE INDEX IF NOT EXISTS idx_appearances_player ON player_appearances(player_id,event_id);
CREATE TABLE IF NOT EXISTS player_stats (
 league TEXT NOT NULL, event_id TEXT NOT NULL, team_id TEXT NOT NULL,
 player_id TEXT NOT NULL, metric TEXT NOT NULL, value INTEGER NOT NULL CHECK(value>=0),
 PRIMARY KEY(league,event_id,team_id,player_id,metric)
);
CREATE TABLE IF NOT EXISTS api_payloads (
 url TEXT PRIMARY KEY, league TEXT, response TEXT NOT NULL, downloaded_at TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('scoreboard','summary'))
);
CREATE TABLE IF NOT EXISTS summary_sync (
 league TEXT NOT NULL, event_id TEXT NOT NULL, checked_at TEXT NOT NULL,
 has_team_stats INTEGER NOT NULL DEFAULT 0, has_player_stats INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(league,event_id)
);
CREATE TABLE IF NOT EXISTS sync_runs (
 run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
 completed_at TEXT, result TEXT, requests INTEGER NOT NULL DEFAULT 0,
 message TEXT
);
