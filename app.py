from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import string
import random
import sqlite3
from datetime import datetime, timedelta
import os
from urllib.parse import urlparse
import qrcode
import json
from io import BytesIO
import base64
import traceback
import logging
from flask_wtf.csrf import CSRFProtect
import traceback

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev_secret_key')

# Use environment variable for database path
DATABASE = os.environ.get('DATABASE_PATH', 'urls.db')

def init_db():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_url TEXT NOT NULL,
                short_url TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                custom_alias TEXT,
                expires_at TIMESTAMP,
                clicks_by_date TEXT
            )
        ''')
        # Add indexes for better performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_short_url ON urls(short_url)')
        conn.commit()

def validate_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def generate_short_url(length=6):
    characters = string.ascii_letters + string.digits
    while True:
        short_url = ''.join(random.choice(characters) for _ in range(length))
        if is_short_url_unique(short_url):
            return short_url

def save_url(original_url, short_url):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO urls (original_url, short_url, created_at) 
            VALUES (?, ?, ?)
        ''', (original_url, short_url, datetime.utcnow()))
        conn.commit()

def get_original_url(short_url):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE urls 
            SET access_count = access_count + 1,
                last_accessed = CURRENT_TIMESTAMP
            WHERE short_url = ? AND is_active = 1
            RETURNING original_url
        ''', (short_url,))
        result = cursor.fetchone()
        return result[0] if result else None

def is_short_url_unique(short_url):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM urls WHERE short_url = ?', (short_url,))
        return cursor.fetchone() is None

def generate_qr_code(url):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

# Add at the top with other imports


# Initialize CSRF protection
csrf = CSRFProtect(app)

# Update the create_url function
@app.route('/create', methods=['POST'])
def create_url():
    try:
        # Add debug logging
        logger.debug(f"Received form data: {request.form}")
        
        data = request.form
        original_url = data.get('original_url')
        custom_alias = data.get('custom_alias')
        expiry_days = data.get('expiry_days', type=int)
        
        # Validate URL
        if not original_url or not validate_url(original_url):
            logger.error(f"Invalid URL: {original_url}")
            return jsonify({'error': 'Invalid URL'}), 400
        
        # Generate or validate short URL
        try:
            if custom_alias:
                if not is_short_url_unique(custom_alias):
                    return jsonify({'error': 'Custom alias already taken'}), 400
                short_url = custom_alias
            else:
                short_url = generate_short_url()
        except Exception as e:
            logger.error(f"Error generating short URL: {str(e)}")
            return jsonify({'error': 'Error generating short URL'}), 500

        # Set expiration
        expires_at = datetime.utcnow() + timedelta(days=expiry_days) if expiry_days else None

        try:
            # Ensure database directory exists
            ensure_db_directory()
            
            with sqlite3.connect(DATABASE) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO urls (
                        original_url, 
                        short_url, 
                        created_at, 
                        expires_at, 
                        custom_alias,
                        clicks_by_date
                    ) VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    original_url,
                    short_url,
                    datetime.utcnow(),
                    expires_at,
                    custom_alias,
                    '{}'  # Initialize empty JSON for clicks_by_date
                ))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}\n{traceback.format_exc()}")
            # Return the specific database error for debugging
            return jsonify({'error': f'Database error: {e}'}), 500

        shortened_url = request.url_root + short_url
        qr_code = generate_qr_code(shortened_url)
        
        # Add success logging
        logger.debug(f"Successfully created short URL: {shortened_url}")
        logger.debug(f"Successfully created short URL: {shortened_url}")
        
        return jsonify({
            'short_url': shortened_url,
            'qr_code': qr_code,
            'expires_at': expires_at.isoformat() if expires_at else None
        })
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': 'Internal server error'}), 500

# Add this function to verify database
def verify_database():
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            return True
    except sqlite3.Error as e:
        logger.error(f"Database verification failed: {e}")
        return False

# Update the setup function
@app.route('/stats/<short_url>')
def url_stats(short_url):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT original_url, created_at, access_count, clicks_by_date
            FROM urls WHERE short_url = ?
        ''', (short_url,))
        result = cursor.fetchone()
        
    if not result:
        return jsonify({'error': 'URL not found'}), 404
        
    return jsonify({
        'original_url': result[0],
        'created_at': result[1],
        'total_clicks': result[2],
        'clicks_by_date': json.loads(result[3] or '{}')
    })

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        original_url = request.form.get('original_url')
        
        if not original_url or not validate_url(original_url):
            flash('Please enter a valid URL including http:// or https://')
            return redirect(url_for('index'))

        short_url = generate_short_url()
        save_url(original_url, short_url)
        
        shortened_url = request.url_root + short_url
        # Ensure proper HTML escaping and data attribute setting
        flash(f'Your shortened URL: <a href="{shortened_url}" data-original-url="{original_url}">{shortened_url}</a>')
        return redirect(url_for('index'))

    return render_template('index.html')

@app.route('/<short_url>')
def redirect_to_url(short_url):
    original_url = get_original_url(short_url)
    if original_url:
        return redirect(original_url)
    flash('Invalid or expired short URL.')
    return redirect(url_for('index'))

@app.before_first_request
def setup():
    ensure_db_directory()
    init_db()
    if not verify_database():
        logger.error("Database verification failed during setup")
# Add after DATABASE definition
def ensure_db_directory():
    db_dir = os.path.dirname(DATABASE)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)

# Call in main
if __name__ == '__main__':
    ensure_db_directory()
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))