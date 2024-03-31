import json
import logging
import sqlite3
import uuid
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Uses https://mainstream.ghan.nl/export.html
# as a primary source of data


logger = logging.getLogger(__name__)
logging.basicConfig(format='%(levelname)s: %(message)s', encoding='utf-8', level=logging.INFO)


def open_loved_tracks(file_path: Path):
    with open(file_path, encoding='utf-8') as f:
        json_out = json.load(f)
        for page in json_out:
            tracks = page.get("track", {}) if isinstance(page, dict) else page
            for track in tracks:
                yield track


def get_user_id(db_cursor: sqlite3.Cursor, user_name: str):
    result = db_cursor.execute(
        f'SELECT u.id FROM user u WHERE u.name="{user_name}"')
    return result.fetchone()[0]


def get_track_id(db_cursor: sqlite3.Cursor, artist: str, name: str, mbz_track_id: str):
    for query in [
        f'SELECT mf.id FROM media_file mf WHERE mf.mbz_release_track_id = "{mbz_track_id}"',
        f'SELECT mf.id FROM media_file mf WHERE (mf.artist= "{artist}") AND (mf.title = "{name}")',
        f'SELECT mf.id FROM media_file mf WHERE (mf.path LIKE "%{artist}%") AND (mf.path LIKE "%{name}%")',
    ]:
        result = db_cursor.execute(query)
        fetch = result.fetchone()
        if fetch is not None:
            return fetch[0]
    return None


def main():
    parser = ArgumentParser(description="Last.FM loved tracks importer")
    parser.add_argument("--tracks-file", type=str, help="JSON with loved tracks")
    parser.add_argument("--db", type=str, help="path to navidrome.db")
    parser.add_argument("--name", type=str, help="Navidrome user name")
    parser.add_argument("--tz", type=str, required=False, help="Timezone")
    args = parser.parse_args()

    db_con = sqlite3.connect(args.db)
    db_cursor = db_con.cursor()
    user_id = get_user_id(db_cursor, args.name)
    loved_tracks = open_loved_tracks(Path(args.tracks_file))

    # output_sql = ('INSERT INTO'
    #               ' annotation'
    #               ' (user_id, item_id, item_type, play_count, play_date, rating, starred, starred_at)'
    #               ' VALUES'
    #               ' ({user_id}, {item_id}, "media_file", {number_of_plays}, {last_played_date}, 0, 1, {loved_date})')

    output_sql = ('INSERT OR REPLACE INTO'
                  ' annotation'
                  ' (ann_id, user_id, item_id, item_type, starred, starred_at)'
                  ' VALUES'
                  ' ("{id}", "{user_id}", "{item_id}", "media_file", 1, "{loved_date}")')

    for track in loved_tracks:
        loved_date = datetime.fromtimestamp(int(track.get("date", {}).get("uts", 0)),
                                            **{"tz": ZoneInfo(args.tz)} if args.tz else {})

        artist = track.get("artist", {}).get("name")
        track_name = track.get("name")
        track_id = get_track_id(db_cursor,
                                artist=artist,
                                name=track_name,
                                mbz_track_id=track.get("mbid"))
        if track_id is None:
            logger.warning('"%s" by "%s" was not found in Navidrome DB', track_name, artist)
            continue

        r = output_sql.format(
            id=uuid.uuid4(),
            user_id=user_id,
            item_id=track_id,
            number_of_plays=0,
            last_played_date=0,
            loved_date=loved_date)

        logger.info('Importing "%s" by "%s"', track_name, artist)
        db_cursor.execute(r)
        db_con.commit()

    db_con.close()


if __name__ == '__main__':
    main()
