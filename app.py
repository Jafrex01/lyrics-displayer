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

# Current scopes
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv('SPOTIFY_CLIENT_ID'),
    client_secret=os.getenv('SPOTIFY_CLIENT_SECRET'),
    redirect_uri=os.getenv('SPOTIFY_REDIRECT_URI'),
    scope='user-read-currently-playing user-read-playback-state'  # These are sufficient
))

# Increase cache time and reduce API calls
CACHE_DURATION = 1.0  # 1 second cache
LYRICS_CACHE_SIZE = 20

@lru_cache(maxsize=LYRICS_CACHE_SIZE)
def get_lrc_lyrics(artist, title):
    try:
        # Direct lyrics fetch without search if possible
        response = requests.get(
            'https://lrclib.net/api/get',
            params={
                'artist_name': artist,
                'track_name': title
            },
            timeout=3  # Add 3 second timeout
        )
        
        if response.status_code == 200:
            lyrics_data = response.json()
            if lyrics_data and 'syncedLyrics' in lyrics_data:
                return parse_lyrics(lyrics_data['syncedLyrics'])
        return None
    except Exception as e:
        print(f"Error fetching lyrics from lrclib: {e}")
        return None

def parse_lyrics(synced_lyrics):
    lines = []
    for line in synced_lyrics.split('\n'):
        if not line.strip():
            continue
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

class PlaybackCache:
    def __init__(self):
        self.data = None
        self.last_update = 0
        self.last_progress = 0

playback_cache = PlaybackCache()

def get_current_playback_with_timeout():
    current_time = time.time()
    
    # Return cached data if it's fresh enough
    if playback_cache.data and (current_time - playback_cache.last_update) < CACHE_DURATION:
        # Update progress time manually instead of fetching
        if playback_cache.data['is_playing']:
            time_diff = (current_time - playback_cache.last_update) * 1000
            playback_cache.data['progress_ms'] = min(
                playback_cache.last_progress + time_diff,
                playback_cache.data['item']['duration_ms']
            )
        return playback_cache.data
    
    try:
        data = sp.current_playback()
        if data:
            playback_cache.data = data
            playback_cache.last_update = current_time
            playback_cache.last_progress = data['progress_ms']
        return data
    except Exception as e:
        print(f"Error in playback: {e}")
        return playback_cache.data

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

# Update the quick endpoint to use cached progress
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
