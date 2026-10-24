"""Import a snapshot of the Fedora JavaFX SQLite DB into the Mobile DB.

STOP the mobile server first. This replaces all mobile history after a backup.
"""
import os
import sqlite3
import sys
from pathlib import Path

if len(sys.argv)!=2:
    sys.exit('Utilizare: python scripts/import_desktop_db.py /cale/catre/football_analyzer.db')
src=Path(sys.argv[1]).expanduser().resolve()
dst=Path(os.environ.get('DATA_DIR',str(Path(__file__).resolve().parents[1]/'data')))/'football_analyzer.db'
if not src.is_file() or src==dst:
    sys.exit('Fișierul sursă lipsește sau coincide cu destinația.')
dst.parent.mkdir(parents=True,exist_ok=True)
# Use SQLite's backup API even if the source was created using WAL mode.
with sqlite3.connect(src) as db:
    for table in ['fixtures','team_stats','player_appearances']:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() is None:
            sys.exit('Baza furnizată nu este compatibilă cu schema Football Analyzer.')
if dst.exists():
    from datetime import datetime,timezone
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    with sqlite3.connect(dst) as db,sqlite3.connect(str(dst)+'.backup-'+stamp) as backup:
        db.backup(backup)
with sqlite3.connect(src) as db,sqlite3.connect(dst) as out:
    db.backup(out)
# Perform any newer schema migrations.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
server.initialize()
print('Baza importată în',dst)
