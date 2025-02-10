from flask import Flask, render_template, jsonify
from spotipy.oauth2 import SpotifyOAuth
import spotipy
import requests
import os
from dotenv import load_dotenv
import time
from functools import lru_cache

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Initialize Spotify client
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv('SPOTIFY_CLIENT_ID'),
    client_secret=os.getenv('SPOTIFY_CLIENT_SECRET'),
    redirect_uri=os.getenv('SPOTIFY_REDIRECT_URI'),
    scope='user-read-currently-playing user-read-playback-state'
))

# Cache lyrics results for 1 hour
@lru_cache(maxsize=100)
def get_lrc_lyrics(artist, title):
    try:
        # Search for lyrics on lrclib.net
        response = requests.get(
            'https://lrclib.net/api/search',
            params={
                'artist_name': artist,
                'track_name': title
            }
        )
        
        if response.status_code == 200:
            results = response.json()
            if results:  # If we found any matches
                # Get the first result's ID
                track_id = results[0]['id']
                
                # Get the actual lyrics
                lyrics_response = requests.get(f'https://lrclib.net/api/get/{track_id}')
                if lyrics_response.status_code == 200:
                    lyrics_data = lyrics_response.json()
                    if 'syncedLyrics' in lyrics_data:
                        # Parse the LRC format into our needed structure
                        lines = []
                        for line in lyrics_data['syncedLyrics'].split('\n'):
                            if line.strip():
                                try:
                                    # Extract timestamp and text
                                    time_part = line[line.find('[')+1:line.find(']')]
                                    text_part = line[line.find(']')+1:].strip()
                                    
                                    # Convert timestamp to milliseconds
                                    minutes, seconds = time_part.split(':')
                                    seconds, ms = seconds.split('.')
                                    total_ms = (int(minutes) * 60 * 1000) + (int(seconds) * 1000) + (int(ms) * 10)
                                    
                                    lines.append({
                                        'startTimeMs': total_ms,
                                        'words': text_part
                                    })
                                except:
                                    continue
                        
                        return lines
        return None
    except Exception as e:
        print(f"Error fetching lyrics from lrclib: {e}")
        return None

def get_current_song():
    try:
        current_track = sp.current_user_playing_track()
        if current_track is not None:
            song_name = current_track['item']['name']
            artist_name = current_track['item']['artists'][0]['name']
            
            # Get album artwork
            album_art = current_track['item']['album']['images'][0]['url'] if current_track['item']['album']['images'] else None
            
            # Get the exact playback position
            playback_state = sp.current_playback()
            exact_progress = playback_state['progress_ms'] if playback_state else current_track['progress_ms']
            
            # Use cached lyrics lookup
            lyrics = get_lrc_lyrics(artist_name, song_name)
            
            return {
                'name': song_name,
                'artist': artist_name,
                'progress_ms': exact_progress,
                'is_playing': current_track['is_playing'],
                'lyrics': lyrics,
                'timestamp': int(time.time() * 1000),  # Add server timestamp
                'album_art': album_art,  # Add album artwork URL
                'duration_ms': current_track['item']['duration_ms']  # Add total duration
            }
        return None
    except Exception as e:
        print(f"Error getting current song: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/current-song')
def current_song():
    song_info = get_current_song()
    if song_info is None:
        return jsonify({'error': 'No song playing'})
    return jsonify(song_info)

if __name__ == '__main__':
    # Use production mode if environment variable is set
    if os.getenv('PRODUCTION'):
        app.run(host='0.0.0.0')
    else:
        app.run(debug=True)
