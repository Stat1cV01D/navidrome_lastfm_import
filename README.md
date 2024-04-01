# navidrome_lastfm_import
Import data from Last.FM into Navidrome DB

Primarily targets "loved tracks" JSON from https://mainstream.ghan.nl/export.html, but other input formats are welcome

## Usage
- Turn down Navidrome
- Backup "navidrome.db" to a safe place (or rename)
- Download "navidrome.db" from your server
- Launch `python main.py --tracks-file=lovedtracks.json --db=path/to/navidrome.db --name=Navidrome_User_Name`
- Upload it back to server
- Turn on Navidrome and see some tracks (not albums) being listed as favorites
