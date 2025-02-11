from flask import Flask, render_template, jsonify, request
from spotipy.oauth2 import SpotifyOAuth
import spotipy
import requests
import os
from dotenv import load_dotenv
import time
from functools import lru_cache
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

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

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///tasks.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Task Model
class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.DateTime, nullable=True)
    completed = db.Column(db.Boolean, default=False)
    priority = db.Column(db.Integer, default=1)  # 1=Low, 2=Medium, 3=High
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Task {self.title}>'

# Create tables before first request
# @app.before_first_request

# Instead, use this approach:
with app.app_context():
    # Put your initialization code here
    # Whatever code was in your before_first_request function should go here

    @lru_cache(maxsize=100)
    def your_function():
        # function code here
        pass

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

# Cache Spotify API results for 1 second
@lru_cache(maxsize=1)
def get_current_playback():
    return sp.current_playback()

def get_current_playback_with_timeout():
    current_time = time.time()
    # Reduce cache time to 0.5 seconds for faster updates
    if hasattr(get_current_playback, 'last_call'):
        if current_time - get_current_playback.last_call < 0.5:  # Reduced from 1.0 to 0.5
            return get_current_playback()
    
    get_current_playback.cache_clear()
    get_current_playback.last_call = current_time
    return get_current_playback()

def get_current_song():
    try:
        # Use the timeout version for consistency
        playback_state = get_current_playback_with_timeout()
        
        if not playback_state or not playback_state['item']:
            return None
            
        current_track = playback_state['item']
        song_name = current_track['name']
        artist_name = current_track['artists'][0]['name']
        
        # Prepare basic response first
        response = {
            'name': song_name,
            'artist': artist_name,
            'progress_ms': playback_state['progress_ms'],
            'is_playing': playback_state['is_playing'],
            'timestamp': int(time.time() * 1000),
            'album_art': current_track['album']['images'][0]['url'] if current_track['album']['images'] else None,
            'duration_ms': current_track['duration_ms']
        }
        
        # Get lyrics asynchronously if needed
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

# Add a new endpoint for faster updates without lyrics
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

# Task Routes
@app.route('/tasks', methods=['GET'])
def get_tasks():
    try:
        tasks = Task.query.filter_by(completed=False).order_by(Task.created_at.desc()).all()
        return jsonify([{
            'id': task.id,
            'title': task.title,
            'description': task.description,
            'due_date': task.due_date.isoformat() if task.due_date else None,
            'completed': task.completed,
            'priority': task.priority,
            'created_at': task.created_at.isoformat() if task.created_at else None
        } for task in tasks])
    except Exception as e:
        print(f"Error fetching tasks: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/tasks', methods=['POST'])
def create_task():
    try:
        data = request.json
        print("Received task data:", data)  # Debug print
        
        # Convert due_date string to datetime if it exists
        due_date = None
        if data.get('due_date'):
            try:
                due_date = datetime.fromisoformat(data['due_date'].replace('Z', '+00:00'))
            except ValueError as e:
                print("Date parsing error:", e)
                due_date = None

        task = Task(
            title=data['title'],
            description=data.get('description', ''),
            due_date=due_date,
            priority=data.get('priority', 1)
        )
        
        db.session.add(task)
        db.session.commit()
        
        return jsonify({
            'message': 'Task created successfully',
            'id': task.id,
            'title': task.title,
            'description': task.description,
            'due_date': task.due_date.isoformat() if task.due_date else None,
            'priority': task.priority
        })
    except Exception as e:
        print("Error creating task:", str(e))  # Debug print
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/tasks/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    try:
        task = Task.query.get_or_404(task_id)
        data = request.json
        
        if 'completed' in data:
            task.completed = data['completed']
        if 'title' in data:
            task.title = data['title']
        if 'description' in data:
            task.description = data['description']
        if 'priority' in data:
            task.priority = data['priority']
        if 'due_date' in data:
            task.due_date = datetime.fromisoformat(data['due_date']) if data['due_date'] else None
        
        db.session.commit()
        return jsonify({'message': 'Task updated successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Add proper database initialization
def init_db():
    with app.app_context():
        try:
            db.create_all()
            print("Database initialized successfully")
        except Exception as e:
            print(f"Error initializing database: {e}")

if __name__ == '__main__':
    init_db()  # Initialize database properly
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
