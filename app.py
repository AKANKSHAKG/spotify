from flask import Flask, render_template, request, jsonify
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import random
import time
from requests.exceptions import RequestException, ReadTimeout, ConnectionError
import os
from dotenv import load_dotenv
app = Flask(__name__)

# ----------------------
# Spotify API Credentials
# ----------------------
load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    raise ValueError("Spotify credentials not found. Check your .env file.")

auth_manager = SpotifyClientCredentials(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET
)

sp = spotipy.Spotify(auth_manager=auth_manager)


# ----------------------
# Convert Spotify track to simple dictionary
# ----------------------
def build_song(track):

    if not track:
        return None

    artists = ", ".join(
        artist["name"] for artist in track.get("artists", [])
    )

    images = track.get("album", {}).get("images", [])

    album_art = images[0]["url"] if images else None

    return {
        "name": track.get("name"),
        "artists": artists,
        "url": track.get("external_urls", {}).get("spotify"),
        "preview_url": track.get("preview_url"),
        "album_art": album_art
    }


# ----------------------
# Retry wrapper for Spotify calls
# ----------------------
def try_spotify_call(fn, *args, retries=3, **kwargs):

    for attempt in range(retries):

        try:
            return fn(*args, **kwargs)

        except (ReadTimeout, ConnectionError, RequestException):

            if attempt < retries - 1:
                time.sleep(1)
            else:
                raise


# ----------------------
# Homepage
# ----------------------
@app.route("/")
def index():
    return render_template("index.html")


# ----------------------
# Get Songs API
# ----------------------
@app.route("/get-songs", methods=["POST"])
def get_songs():

    data = request.get_json()

    mood = data.get("mood", "").strip()
    language = data.get("language", "").strip()

    if not mood and not language:
        return jsonify({"error": "Enter a mood or language"}), 400

    search_query = f"{mood} {language}".strip()

    try:

        # Search playlists
        search_results = try_spotify_call(
            sp.search,
            q=search_query,
            type="playlist",
            limit=10
        )

        playlists = search_results["playlists"]["items"]

        songs = []

        if playlists:

            # choose random playlist
            playlist = random.choice(playlists)

            playlist_id = playlist["id"]

            playlist_data = try_spotify_call(
                sp.playlist_items,
                playlist_id,
                limit=50
            )

            for item in playlist_data["items"]:

                track = item.get("track")

                if not track:
                    continue

                song = build_song(track)

                if song:
                    songs.append(song)

        # If playlist songs found
        if songs:

            random.shuffle(songs)

            return jsonify({
                "source": "playlist",
                "songs": songs[:10]
            })

        # ----------------------
        # Fallback: Track search
        # ----------------------

        offset = random.randint(0, 20)

        track_results = try_spotify_call(
            sp.search,
            q=search_query,
            type="track",
            limit=20,
            offset=offset
        )

        tracks = track_results["tracks"]["items"]

        songs = []

        for t in tracks:

            song = build_song(t)

            if song:
                songs.append(song)

        if songs:

            random.shuffle(songs)

            return jsonify({
                "source": "track",
                "songs": songs[:10]
            })

        return jsonify({"error": "No songs found"}), 404

    except Exception as e:

        print("Error:", e)

        return jsonify({
            "error": "Server error while fetching songs"
        }), 500


# ----------------------
# Run App
# ----------------------
if __name__ == "__main__":
    app.run(debug=True)