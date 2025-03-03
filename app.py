from flask import Flask, render_template, jsonify, request
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
            if results:
                track_id = results[0]['id']
                lyrics_response = requests.get(f'https://lrclib.net/api/get/{track_id}')
                if lyrics_response.status_code == 200:
                    lyrics_data = lyrics_response.json()
                    if 'syncedLyrics' in lyrics_data:
                        lines = []
                        for line in lyrics_data['syncedLyrics'].split('\n'):
                            if line.strip():
                                try:
                                    time_part = line[line.find('[')+1:line.find(']')]
                                    text_part = line[line.find(']')+1:].strip()
                                    
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

@lru_cache(maxsize=1)
def get_current_playback():
    return sp.current_playback()

def get_current_playback_with_timeout():
    current_time = time.time()
    if hasattr(get_current_playback, 'last_call'):
        if current_time - get_current_playback.last_call < 0.5:
            return get_current_playback()
    
    get_current_playback.cache_clear()
    get_current_playback.last_call = current_time
    return get_current_playback()

def get_current_song():
    try:
        playback_state = get_current_playback_with_timeout()
        
        if not playback_state or not playback_state['item']:
            return None
            
        current_track = playback_state['item']
        song_name = current_track['name']
        artist_name = current_track['artists'][0]['name']
        
        response = {
            'name': song_name,
            'artist': artist_name,
            'progress_ms': playback_state['progress_ms'],
            'is_playing': playback_state['is_playing'],
            'timestamp': int(time.time() * 1000),
            'album_art': current_track['album']['images'][0]['url'] if current_track['album']['images'] else None,
            'duration_ms': current_track['duration_ms']
        }
        
        lyrics = get_lrc_lyrics(artist_name, song_name)
        if lyrics:
            response['lyrics'] = lyrics
        
        return response
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

@app.route('/current-song-quick')
def current_song_quick():
    try:
        playback_state = get_current_playback_with_timeout()
        if not playback_state or not playback_state['item']:
            return jsonify({'error': 'No song playing'})
            
        current_track = playback_state['item']
        return jsonify({
            'name': current_track['name'],
            'artist': current_track['artists'][0]['name'],
            'progress_ms': playback_state['progress_ms'],
            'is_playing': playback_state['is_playing'],
            'timestamp': int(time.time() * 1000),
            'album_art': current_track['album']['images'][0]['url'] if current_track['album']['images'] else None,
            'duration_ms': current_track['duration_ms']
        })
    except Exception as e:
        print(f"Error getting quick song update: {e}")
        return jsonify({'error': 'Error fetching song data'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
