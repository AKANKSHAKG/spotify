from flask import Flask, render_template, request, jsonify
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import time
from requests.exceptions import RequestException, ReadTimeout, ConnectionError

app = Flask(__name__)

# ----------------------
# Replace these with your Spotify keys (hardcoded as requested)
# ----------------------
CLIENT_ID = "691c72891d694610998d89506bb65a89"
CLIENT_SECRET = "a80d962f58624964aed68d90c97028c5"

auth_manager = SpotifyClientCredentials(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)

# Try to construct Spotify client with a larger internal timeout if supported.
# If your spotipy version doesn't accept `requests_timeout`, fall back gracefully.
try:
    sp = spotipy.Spotify(auth_manager=auth_manager, requests_timeout=10)
except TypeError:
    sp = spotipy.Spotify(auth_manager=auth_manager)


# Helper: convert a Spotify track object -> compact dict
def build_song(track):
    if not track:
        return None
    artists = ", ".join(a.get("name", "") for a in (track.get("artists") or []))
    images = ((track.get("album") or {}).get("images")) or []
    album_art = images[0]["url"] if images else None
    return {
        "name": track.get("name"),
        "artists": artists,
        "url": (track.get("external_urls") or {}).get("spotify"),
        "preview_url": track.get("preview_url"),
        "album_art": album_art
    }


# Helper: call a spotipy function with retries on network errors
def try_spotify_call(fn, *args, retries=3, backoff=1, **kwargs):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return fn(*args, **kwargs)
        except (ReadTimeout, ConnectionError, RequestException) as e:
            last_exc = e
            app.logger.warning(f"Spotify request failed (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
            else:
                raise
        except Exception as e:
            # non-network error, log and raise
            app.logger.exception("Unexpected error calling Spotify:")
            raise
    # if we exit loop without return:
    raise last_exc


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/get-songs", methods=["POST"])
def get_songs():
    payload = request.get_json(silent=True) or {}
    mood = (payload.get("mood") or "").strip()
    language = (payload.get("language") or "").strip()

    if not mood and not language:
        return jsonify({"error": "Please provide at least a mood or a language."}), 400

    search_query = " ".join(x for x in [mood, language] if x).strip()

    # 1) Try playlist search (several attempts handled inside try_spotify_call)
    try:
        search = try_spotify_call(sp.search, q=search_query, type="playlist", limit=5)
    except RequestException as e:
        app.logger.exception("Spotify search failed completely")
        return jsonify({"error": f"Spotify request failed (network/timeout): {e}"}), 502
    except Exception as e:
        app.logger.exception("Spotify search unexpected error")
        return jsonify({"error": f"Spotify error: {e}"}), 500

    playlists = (search.get("playlists") or {}).get("items", [])
    if playlists:
        # choose playlist with most tracks (followers aren't always available in search)
        def tracks_total(p): 
            try:
                return int((p.get("tracks") or {}).get("total", 0))
            except Exception:
                return 0
        best = max(playlists, key=tracks_total)
        playlist_id = best.get("id")
        playlist_url = (best.get("external_urls") or {}).get("spotify")

        try:
            tracks_data = try_spotify_call(sp.playlist_items, playlist_id, limit=15)
        except RequestException as e:
            app.logger.warning("Fetching playlist items timed out or failed, falling back to track search")
            tracks_data = None
        except Exception as e:
            app.logger.exception("Unexpected error fetching playlist items")
            tracks_data = None

        songs = []
        if tracks_data:
            for it in tracks_data.get("items", []):
                track = it.get("track")
                if not track or track.get("is_local"):
                    continue
                s = build_song(track)
                if s:
                    songs.append(s)

        if songs:
            return jsonify({
                "source": "playlist",
                "playlist_id": playlist_id,
                "playlist_url": playlist_url,
                "songs": songs
            })

    # 2) Fallback: do a track search (try multiple times)
    try:
        res_tracks = try_spotify_call(sp.search, q=search_query, type="track", limit=15)
    except RequestException as e:
        app.logger.exception("Track search failed")
        return jsonify({"error": f"Spotify request failed (network/timeout): {e}"}), 502
    except Exception as e:
        app.logger.exception("Unexpected error during track search")
        return jsonify({"error": f"Spotify error: {e}"}), 500

    tracks = (res_tracks.get("tracks") or {}).get("items", [])
    songs = [build_song(t) for t in tracks if t]
    if songs:
        return jsonify({"source": "track-search", "songs": songs})

    # Nothing found
    return jsonify({"error": f"No playlists or tracks found for: {search_query}"}), 404


if __name__ == "__main__":
    # Keep debug=True while developing so you see server logs
    app.run(debug=True)
