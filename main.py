import json
import logging
import re
import sqlite3
import uuid
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path

# Uses https://mainstream.ghan.nl/export.html
# as a primary source of data


logger = logging.getLogger(__name__)
logging.basicConfig(format='%(levelname)s: %(message)s', filename="output.log",
                    encoding='utf-8', level=logging.DEBUG)


def open_tracks(file_path: Path):
    with open(file_path, encoding='utf-8') as f:
        json_out = json.load(f)
        for page in json_out:
            tracks = page.get("track", {}) if isinstance(page, dict) else page
            for track in tracks:
                yield track


def get_user_id(db_cursor: sqlite3.Cursor, user_name: str):
    result = db_cursor.execute(
        'SELECT u.id FROM user u WHERE u.name = ?', [user_name])
    row = result.fetchone()
    if not row:
        logger.critical("User %s was not found in Naviddrome DB", user_name)
        return None
    return row[0]


def try_get_track_play_count_date(db_cursor: sqlite3.Cursor, track_id: str):
    result = db_cursor.execute(f'SELECT a.play_count, a.play_date FROM annotation a'
                               ' WHERE (a.item_id=:track_id) AND (a.item_type="media_file")',
                               {"track_id": track_id})
    return result.fetchone()


def get_track_id(db_cursor: sqlite3.Cursor, artist: str, name: str, mbz_track_id: str):
    def search_in_path(artist: str, name: str):
        def sanitized(name: str, replace: str):
            for c in r'\/:*?"<>|':
                name = name.replace(c, replace)
            return name

        name = name.lower()
        artist = artist.lower()
        query = ('SELECT mf.id, mf.artist, mf.title FROM media_file mf'
                 ' WHERE (LOWER(mf.path) LIKE :artist) AND ('
                 ' (LOWER(mf.path) LIKE :name)'
                 ' OR (LOWER(mf.path) LIKE :name_sanitized_1)'
                 ' OR (LOWER(mf.path) LIKE :name_sanitized_2)'
                 ')')
        if not "mix" in name:
            query += (' AND (NOT ('
                      '(LOWER(mf.path) LIKE "%(mix by %")'
                      ' OR (LOWER(mf.path) LIKE "%(remix by %")'
                      ' OR (LOWER(mf.path) LIKE "% remix)%")'
                      ' OR (LOWER(mf.path) LIKE "% mix)%")'
                      '))')
        if not "live" in name:
            query += (' AND (NOT LOWER(mf.path) LIKE "%(%live%)%")')
        return (query, {
            "artist": f'%{artist}%',
            "name": f'%{name}%',
            "name_sanitized_1": f'%{sanitized(name, "_")}%',
            "name_sanitized_2": f'%{sanitized(name, "")}%',
        })

    def search_several_artists(artist: str, name: str):
        if not "," in artist:
            return None
        first_artist = artist.split(",")[0].lower()
        name = name.lower()
        return (('SELECT mf.id, mf.artist, mf.title FROM media_file mf WHERE ('
                 '(LOWER(mf.artist) = :first_artist)'
                 ') AND ('
                 '(LOWER(mf.title) = :name) OR (LOWER(mf.title) LIKE :name_feat)'
                 ' OR (LOWER(mf.title) LIKE :name_featuring) OR (LOWER(mf.title) LIKE :name_ft)'
                 ' OR (LOWER(mf.title) LIKE :name_w)'
                 ')'),
                {"first_artist": first_artist,
                    "name": name,
                    "name_feat": f'{name}%feat%',
                    "name_featuring": f'{name}%featuring%',
                    "name_ft": f'{name}%ft%',
                    "name_w": f'{name}%w/%'})

    def search_several_artists_regex(artist: str, name: str):
        delimiters = re.compile(r"(?:[\&\,]| x |ft|feat(?:uring)?| w\/ )", flags=re.IGNORECASE)
        if not delimiters.search(artist + " - " + name):
            return None
        key_words = [x.strip().strip("()[]").lower() for x in delimiters.split(artist + "," + name)]
        template = ('SELECT mf.id, mf.artist, mf.title,'
                    ' LOWER(mf.artist || " " || mf.title) as search_string'
                    ' FROM media_file mf WHERE ({condition})')
        result_query = template.format(condition=") AND (".join(
            f'search_string LIKE ?' for _ in range(len(key_words))
        ))
        return (result_query, [f"%{x}%" for x in key_words])

    queries: list = [
        ('SELECT mf.id, mf.artist, mf.title'
            ' FROM media_file mf WHERE mf.mbz_recording_id = :mbz_track_id',
            {"mbz_track_id": mbz_track_id if mbz_track_id else "None"}),
        ('SELECT mf.id, mf.artist, mf.title'
            ' FROM media_file mf WHERE (LOWER(mf.artist) = :artist) AND (LOWER(mf.title) = :name)',
            {"artist": artist.lower(), "name": name.lower()}),
        search_in_path(artist, name),
        search_several_artists(artist, name),
        search_several_artists_regex(artist, name),
    ]

    try:
        for n, query in enumerate(queries):
            if not query:
                continue
            result = db_cursor.execute(*query)
            fetch = result.fetchone()
            if fetch is not None:
                logger.debug('Found (attempt #%s) ["%s" by "%s"] as ["%s" by "%s"]',
                             n+1, name, artist, fetch[2], fetch[1])
                return fetch[0]
    except sqlite3.OperationalError as e:
        logger.error('Error finding ["%s" by "%s"]: %s', name, artist, str(e))

    return None


def main():
    parser = ArgumentParser(description="Last.FM loved and scrobbled tracks importer")
    parser.add_argument("--loved-tracks-file", type=str, help="JSON with loved tracks")
    parser.add_argument("--scrobbled-tracks-file", type=str, help="JSON with scrobbled tracks")
    parser.add_argument("--db", type=str, help="path to navidrome.db")
    parser.add_argument("--name", type=str, help="Navidrome user name")
    args = parser.parse_args()

    db_con = sqlite3.connect(args.db)
    db_cursor = db_con.cursor()
    user_id = get_user_id(db_cursor, args.name)
    if not user_id:
        logger.error("Failed to retrieve user ID. Exiting.")
        return

    loved_tracks = open_tracks(Path(args.loved_tracks_file))
    scrobbled_tracks = open_tracks(Path(args.scrobbled_tracks_file))

    # Dictionary to hold track data by track ID
    tracks_data = {}

    imported_count = 0
    scrobbled_tracks_count = 0
    for track in scrobbled_tracks:
        scrobbled_tracks_count += 1
        artist = track.get("artist", {}).get("#text")
        track_name = track.get("name")
        mbz_track_id = track.get("mbid")
        play_date = datetime.fromtimestamp(int(track.get("date", {}).get("uts")), tz=timezone.utc)

        if not artist or not track_name:
            logger.warning('"%s" by "%s" is an invalid entry', track_name, artist)
            continue

        track_id = get_track_id(db_cursor, artist, track_name, mbz_track_id)
        if not track_id:
            logger.warning('"%s" by "%s" was not found in Navidrome DB', track_name, artist)
            continue

        imported_count += 1
        if track_id not in tracks_data:
            tracks_data[track_id] = {'play_count': 0, 'latest_play_date': None}

        tracks_data[track_id]['play_count'] += 1
        if not tracks_data[track_id]['latest_play_date'] or tracks_data[track_id]['latest_play_date'] < play_date:
            tracks_data[track_id]['latest_play_date'] = play_date

    logger.info('Processed %s out of %s scrobbles', imported_count, scrobbled_tracks_count)

    imported_count = 0
    loved_tracks_count = 0
    for track in loved_tracks:
        loved_tracks_count += 1
        artist = track.get("artist", {}).get("name") or track.get("artist", {}).get("#text")
        track_name = track.get("name")
        mbz_track_id = track.get("mbid")

        if not artist or not track_name:
            logger.warning('"%s" by "%s" is an invalid entry', track_name, artist)
            continue

        track_id = get_track_id(db_cursor, artist, track_name, mbz_track_id)
        if not track_id:
            logger.warning('"%s" by "%s" was not found in Navidrome DB', track_name, artist)
            continue

        imported_count += 1
        loved_date = datetime.fromtimestamp(int(track.get("date", {}).get("uts")), tz=timezone.utc)

        if track_id not in tracks_data:
            tracks_data[track_id] = {'play_count': 0, 'latest_play_date': None}

        tracks_data[track_id]['starred'] = True
        tracks_data[track_id]['starred_at'] = loved_date

    logger.info('Processed %s out of %s loved tracks', imported_count, loved_tracks_count)

    output_sql = (
        'INSERT OR REPLACE INTO'
        ' annotation'
        ' (ann_id, user_id, item_id, item_type, starred, starred_at, play_count, play_date)'
        ' VALUES'
        ' ("{id}", "{user_id}", "{item_id}", "media_file", {starred}, "{starred_at}", {play_count}, "{play_date}")'
    )

    for track_id, data in tracks_data.items():
        logger.info('Importing track with ID %s', track_id)
        db_cursor.execute(output_sql.format(
            id=uuid.uuid4(),
            user_id=user_id,
            item_id=track_id,
            starred=1 if data.get('starred') else 0,
            starred_at=data.get('starred_at', datetime.min.replace(tzinfo=timezone.utc)),
            play_count=data['play_count'],
            play_date=data['latest_play_date'].isoformat()))
        db_con.commit()

    logger.info('Import complete')
    db_cursor.close()
    db_con.close()


if __name__ == '__main__':
    main()
