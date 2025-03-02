# navidrome_lastfm_import
Import loved tracks and scrobbled tracks from Last.FM into Navidrome DB

Primarily targets "loved tracks" and "scrobbled tracks" JSON files from https://mainstream.ghan.nl/export.html, but other input formats are welcome.

## Usage
1. Turn down Navidrome.
2. Backup "navidrome.db" to a safe place (or rename).
3. Download "navidrome.db" from your server.
4. Launch the script with the appropriate command line arguments:
   ```bash
   python main.py --loved-tracks-file=lovedtracks.json --scrobbled-tracks-file=scrobbledtracks.json --db=path/to/navidrome.db --name=Navidrome_User_Name
   ```
5. Upload the updated "navidrome.db" back to your server.
6. Turn on Navidrome and see tracks (not albums) being listed as favorites with play counts (including the last played date).

## Command Line Arguments
- `--loved-tracks-file`: Path to the JSON file containing loved tracks exported from Last.FM.
- `--scrobbled-tracks-file`: Path to the JSON file containing scrobbled tracks exported from Last.FM.
- `--db`: Path to the Navidrome database file (`navidrome.db`).
- `--name`: Name of the Navidrome user for whom you are importing data.
- `--log-level`: Set the logging level (default is "info").
