import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine, MetaData, select, update, insert
from sqlalchemy.orm import sessionmaker

# Add app to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import MediaRequest, LibraryItem, PlexUser, DownloadHistory
from app.legacy_migration import postgres_sync_url

def main():
    sqlite_path = Path("data/plex_rss.db").resolve()
    pg_url = os.environ.get("DATABASE_URL", "postgresql://plexrss:plexrss@db:5432/plexrss")
    pg_url = postgres_sync_url(pg_url)

    if not sqlite_path.exists():
        print(f"Error: {sqlite_path} does not exist.")
        return

    print("Connecting to databases...")
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    pg_engine = create_engine(pg_url)
    Session = sessionmaker(bind=pg_engine)
    
    with Session() as pg_session:
        # 1. USERS
        print("\n--- Users ---")
        sqlite_users = sqlite_conn.execute("SELECT * FROM plex_users").fetchall()
        pg_users = {u.plex_user_id: u for u in pg_session.query(PlexUser).all()}
        
        users_inserted = 0
        for sq_u in sqlite_users:
            if sq_u['plex_user_id'] not in pg_users:
                new_user = PlexUser(
                    plex_user_id=sq_u['plex_user_id'],
                    display_name=sq_u['display_name'],
                    plex_email=sq_u['plex_email'],
                    notification_email=sq_u['notification_email'],
                    enabled=sq_u['enabled'],
                    custom_name=sq_u['custom_name'],
                    source=sq_u['source'],
                    role=sq_u['role'],
                    can_login=sq_u['can_login']
                )
                pg_session.add(new_user)
                users_inserted += 1
        
        pg_session.commit()
        print(f"Inserted {users_inserted} missing users.")

        # 2. LIBRARY ITEMS MAPPING
        print("\n--- Library Items Mapping ---")
        sqlite_lib = sqlite_conn.execute("SELECT id, title, year, media_type FROM library_items").fetchall()
        sq_lib_map = {row['id']: row for row in sqlite_lib}
        
        pg_lib = pg_session.query(LibraryItem).all()
        pg_lib_map = {}
        for row in pg_lib:
            key = (row.title, row.year, row.media_type)
            pg_lib_map[key] = row.id

        lib_id_mapping = {}
        for sq_id, row in sq_lib_map.items():
            key = (row['title'], row['year'], row['media_type'])
            if key in pg_lib_map:
                lib_id_mapping[sq_id] = pg_lib_map[key]

        print(f"Mapped {len(lib_id_mapping)} library items between DBs.")

        # 3. MEDIA REQUESTS
        print("\n--- Media Requests ---")
        sqlite_reqs = sqlite_conn.execute("SELECT * FROM media_requests").fetchall()
        pg_reqs = pg_session.query(MediaRequest).all()
        
        pg_reqs_keys = set()
        for r in pg_reqs:
            if r.tmdb_id:
                pg_reqs_keys.add(f"tmdb:{r.tmdb_id}")
            elif r.tvdb_id:
                pg_reqs_keys.add(f"tvdb:{r.tvdb_id}")
            else:
                pg_reqs_keys.add(f"title:{r.title}:{r.year}")

        reqs_inserted = 0
        for sq_r in sqlite_reqs:
            key = None
            if sq_r['tmdb_id']:
                key = f"tmdb:{sq_r['tmdb_id']}"
            elif sq_r['tvdb_id']:
                key = f"tvdb:{sq_r['tvdb_id']}"
            else:
                key = f"title:{sq_r['title']}:{sq_r['year']}"
                
            if key not in pg_reqs_keys:
                new_lib_id = None
                if sq_r['library_item_id']:
                    new_lib_id = lib_id_mapping.get(sq_r['library_item_id'])

                new_req = MediaRequest(
                    plex_user_id=sq_r['plex_user_id'],
                    plex_user=sq_r['plex_user'],
                    title=sq_r['title'],
                    year=sq_r['year'],
                    media_type=sq_r['media_type'],
                    tmdb_id=sq_r['tmdb_id'],
                    tvdb_id=sq_r['tvdb_id'],
                    imdb_id=sq_r['imdb_id'],
                    status=sq_r['status'],
                    source=sq_r['source'],
                    arr_id=sq_r['arr_id'],
                    arr_slug=sq_r['arr_slug'],
                    requested_at=sq_r['requested_at'],
                    available_at=sq_r['available_at'],
                    poster_url=sq_r['poster_url'],
                    overview=sq_r['overview'],
                    extra_requesters=sq_r['extra_requesters'],
                    library_item_id=new_lib_id
                )
                pg_session.add(new_req)
                pg_reqs_keys.add(key)
                reqs_inserted += 1

        pg_session.commit()
        print(f"Inserted {reqs_inserted} missing media requests.")

        # 4. DOWNLOAD HISTORY
        print("\n--- Download History ---")
        sqlite_hist = sqlite_conn.execute("SELECT * FROM download_history").fetchall()
        pg_hist = pg_session.query(DownloadHistory).all()
        
        pg_hist_keys = { (h.title, h.media_type) for h in pg_hist }
        hist_inserted = 0
        
        for sq_h in sqlite_hist:
            key = (sq_h['title'], sq_h['media_type'])
            if key not in pg_hist_keys:
                new_hist = DownloadHistory(
                    title=sq_h['title'],
                    year=sq_h['year'],
                    media_type=sq_h['media_type'],
                    source=sq_h['source'],
                    instance_name=sq_h['instance_name'],
                    poster_url=sq_h['poster_url'],
                    completed_at=sq_h['completed_at']
                )
                pg_session.add(new_hist)
                pg_hist_keys.add(key)
                hist_inserted += 1
                
        pg_session.commit()
        print(f"Inserted {hist_inserted} missing download history records.")

if __name__ == '__main__':
    main()
