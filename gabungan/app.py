from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import pyrebase
import firebase_admin
from firebase_admin import credentials, firestore, storage
import os
from uuid import uuid4
from dotenv import load_dotenv
import google.generativeai as genai
import logging
import json

app = Flask(__name__, template_folder='templates')
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'fallback_secret_key')

# Load environment variables
load_dotenv(dotenv_path='E:\\tugas\\gabungan\\.env')

# Configure Firebase
firebaseConfig = {
    'apiKey': os.getenv('FIREBASE_API_KEY'),
    'authDomain': os.getenv('FIREBASE_AUTH_DOMAIN'),
    'databaseURL': os.getenv('FIREBASE_DATABASE_URL'),
    'projectId': os.getenv('FIREBASE_PROJECT_ID'),
    'storageBucket': os.getenv('FIREBASE_STORAGE_BUCKET'),
    'messagingSenderId': os.getenv('FIREBASE_MESSAGING_SENDER_ID'),
    'appId': os.getenv('FIREBASE_APP_ID'),
    'measurementId': os.getenv('FIREBASE_MEASUREMENT_ID')
}

firebase = pyrebase.initialize_app(firebaseConfig)
auth = firebase.auth()
db_rtdb = firebase.database()  # Realtime Database

# Initialize Firebase Admin
service_account_info = json.loads(os.getenv('FIREBASE_SERVICE_ACCOUNT', '{}'))
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred, {'storageBucket': os.getenv('FIREBASE_STORAGE_BUCKET')})
db_firestore = firestore.client()
bucket = storage.bucket()

# Configure Chatbot
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("No API Key found in environment variables or .env file.")

genai.configure(api_key=api_key)

generation_config = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 8192,
    "response_mime_type": "text/plain",
}

model = genai.GenerativeModel(
    model_name="gemini-1.5-pro",
    generation_config=generation_config,
)
users = {
    'admin': {'username': 'admin', 'password': '123', 'role': 'admin'},
}
# # Admin credentials
# username = "admin"
# password = "123"

@app.route('/')
def home():
    return render_template('index.html')

### Profile Routes
@app.route('/profile')
def profile_index():
    user_data = db_rtdb.child("users").child("user_id").get().val()
    return render_template('profile.html', user_data=user_data)

@app.route('/profile/edit', methods=['GET', 'POST'])
def profile_edit():
    if request.method == 'POST':
        # Ambil data dari form
        name = request.form['name']
        profession = request.form['profession']
        bio = request.form['bio']
        
        # Update data di Firebase
        db_rtdb.child("users").child("user_id").update({
            "name": name,
            "profession": profession,
            "bio": bio
        })
        return redirect(url_for('profile_index'))
    
    user_data = db_rtdb.child("users").child("user_id").get().val()
    return render_template('edit.html', user_data=user_data)

### Microblog Routes
@app.route('/microblog')
def microblog_index():
    blocks_ref = db_firestore.collection('microblocks')
    blocks = blocks_ref.stream()
    block_list = [{'id': block.id, **block.to_dict()} for block in blocks]
    return render_template('micro_blog.html', blocks=block_list)

@app.route('/microblog/add-block', methods=['POST'])
def microblog_add_block():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    image = request.files.get('image')

    if not title or not content:
        return render_template('micro_blog.html', blocks=[], error="Title and content are required.")

    # Handling image upload
    image_url = None
    if image and image.filename != '':
        filename = str(uuid4()) + os.path.splitext(image.filename)[1]
        blob = bucket.blob(filename)
        blob.upload_from_file(image)
        blob.make_public()
        image_url = blob.public_url

    # Save data to Firestore
    db_firestore.collection('microblocks').add({
        'title': title,
        'content': content,
        'image_url': image_url
    })
    return redirect(url_for('microblog_index'))

@app.route('/microblog/delete-block/<block_id>', methods=['POST'])
def microblog_delete_block(block_id):
    print(f"Deleting block with ID: {block_id}")  # Debug print
    block_ref = db_firestore.collection('microblocks').document(block_id)
    block = block_ref.get()

    if block.exists:
        block_data = block.to_dict()
        if block_data.get('image_url'):
            # Delete the image from storage
            filename = block_data['image_url'].split('/')[-1]
            blob = bucket.blob(filename)
            blob.delete()

        # Delete the block
        block_ref.delete()
    
    return redirect(url_for('microblog_index'))

### Upload Certificate Routes
@app.route('/sertifikat')
def sertifikat_index():
    images_ref = db_firestore.collection('images')
    images = images_ref.stream()
    images_list = [img.to_dict() for img in images]
    return render_template('sertifikat.html', images=images_list)

@app.route('/sertifikat/upload', methods=['POST'])
def sertifikat_upload_image():
    if 'image' not in request.files:
        return "No image part", 400
    
    image = request.files['image']
    if image.filename == '':
        return "No selected file", 400
    
    filename = str(uuid4()) + os.path.splitext(image.filename)[1]
    blob = bucket.blob(filename)
    blob.upload_from_file(image)
    blob.make_public()
    
    db_firestore.collection('images').document(filename).set({
        'filename': filename,
        'url': blob.public_url
    })

    return redirect(url_for('sertifikat_index'))

@app.route('/sertifikat/delete/<filename>', methods=['POST'])
def sertifikat_delete_image(filename):
    blob = bucket.blob(filename)
    blob.delete()
    db_firestore.collection('images').document(filename).delete()
    return redirect(url_for('sertifikat_index'))

### Chatbot Routes
@app.route('/chatbot')
def chatbot_index():
    return render_template('chatbot.html')

@app.route('/chatbot/chat', methods=['POST'])
def chatbot_chat():
    try:
        user_input = request.json.get('message')
        if not user_input:
            return jsonify({'response': 'Please enter a message.'}), 400

        chat_session = model.start_chat(history=[])
        response = chat_session.send_message(user_input)
        return jsonify({'response': response.text})
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        return jsonify({'response': f'An internal error occurred: {e}'}), 500

### Portfolio Routes
@app.route('/portfolio')
def portfolio_index():
    return render_template('porto.html')
# Fungsi untuk memeriksa login
def check_login(username, password):
    user = users.get(username)
    if user and user['password'] == password:
        return user
    return None

### Login Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = check_login(username, password)
        
        if user:
            session['user_id'] = username
            session['role'] = user['role']
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_dashboard'))
        else:
            error = "Login gagal! Periksa username dan password Anda."
            return render_template('login.html', error=error, correct_credentials=users)

    return render_template('login.html')
@app.route('/admin')
def admin_dashboard():
    if 'user_id' in session and session['role'] == 'admin':
        # Fetch Profile Data
        profiles_ref = db_rtdb.child("users").get()
        profiles = profiles_ref.val()

        # Fetch Microblog Data
        microblogs_ref = db_firestore.collection('microblocks').stream()
        microblogs = [{'id': block.id, **block.to_dict()} for block in microblogs_ref]

        # Fetch Certificate Data
        certificates_ref = db_firestore.collection('images').stream()
        certificates = [{'filename': img.id, **img.to_dict()} for img in certificates_ref]

        return render_template('admin_dashboard.html', profiles=profiles, microblogs=microblogs, certificates=certificates)
    else:
        return redirect(url_for('login'))

@app.route('/admin/add-microblog', methods=['POST'])
def admin_add_microblog():
    if 'user_id' in session and session['role'] == 'admin':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        image = request.files.get('image')

        if not title or not content:
            return render_template('admin_dashboard.html', error="Title and content are required.")

        # Handling image upload
        image_url = None
        if image and image.filename != '':
            filename = str(uuid4()) + os.path.splitext(image.filename)[1]
            blob = bucket.blob(filename)
            blob.upload_from_file(image)
            blob.make_public()
            image_url = blob.public_url

        # Save data to Firestore
        db_firestore.collection('microblocks').add({
            'title': title,
            'content': content,
            'image_url': image_url
        })
        return redirect(url_for('admin_dashboard'))
    else:
        return redirect(url_for('login'))

@app.route('/admin/add-sertifikat', methods=['POST'])
def admin_add_sertifikat():
    if 'user_id' in session and session['role'] == 'admin':
        image = request.files.get('image')

        if not image or image.filename == '':
            return render_template('admin_dashboard.html', error="Image is required.")

        filename = str(uuid4()) + os.path.splitext(image.filename)[1]
        blob = bucket.blob(filename)
        blob.upload_from_file(image)
        blob.make_public()

        db_firestore.collection('images').document(filename).set({
            'filename': filename,
            'url': blob.public_url
        })

        return redirect(url_for('admin_dashboard'))
    else:
        return redirect(url_for('login'))

# Delete Profile
@app.route('/admin/delete-profile/<user_id>', methods=['POST'])
def admin_delete_profile(user_id):
    db_rtdb.child("users").child(user_id).remove()
    return redirect(url_for('admin_dashboard'))

# Delete Microblog
@app.route('/admin/delete-microblog/<block_id>', methods=['POST'])
def admin_delete_microblog(block_id):
    block_ref = db_firestore.collection('microblocks').document(block_id)
    block_ref.delete()
    return redirect(url_for('admin_dashboard'))

# Delete Certificate
@app.route('/admin/delete-certificate/<filename>', methods=['POST'])
def admin_delete_certificate(filename):
    blob = bucket.blob(filename)
    blob.delete()
    db_firestore.collection('images').document(filename).delete()
    return redirect(url_for('admin_dashboard'))

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
