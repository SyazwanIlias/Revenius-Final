import os
import json
import re
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import mysql.connector
from werkzeug.utils import secure_filename

import google.generativeai as genai
import PyPDF2
import docx
import markdown
from markupsafe import Markup

app = Flask(__name__)

# --- markdown filter ---
@app.template_filter('markdown')
def to_markdown(text):
    return Markup(markdown.markdown(text))

# --- 1. CONFIGURATION ---
app.secret_key = 'your_secret_key'

# Replace with your actual valid API Key
os.environ["GEMINI_API_KEY"] = "AIzaSyD3rhNGyRzdoIBc3zNSARETI_zk7y19DF0" 
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# Database Connection
def get_db_connection():
    return mysql.connector.connect(
        host='localhost', user='root', password='', database='revenius_db'
    )

# File Upload Logic
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Extract Text Helper
def extract_text_from_file(file_path):
    ext = file_path.rsplit('.', 1)[1].lower()
    text = ""
    
    try:
        if ext == 'pdf':
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
        elif ext == 'docx':
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif ext == 'txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"
        
    return text

# --- ROUTES ---

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    msg = ''
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form:
        username = request.form['username']
        password = request.form['password']
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute('SELECT * FROM users WHERE username = %s AND password = %s', (username, password))
            account = cursor.fetchone()
            cursor.close()
            conn.close()
            if account:
                session['loggedin'] = True
                session['id'] = account['user_id']
                session['username'] = account['username']
                return redirect(url_for('dashboard'))
            else:
                msg = 'Invalid Login. Try again.'
        except mysql.connector.Error as err:
            msg = f"Database Error: {err}"
    return render_template('login.html', msg=msg)

@app.route('/register', methods=['GET', 'POST'])
def register():
    msg = ''
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validation
        if not username or not email or not password or not confirm_password:
            msg = 'Please fill out all fields!'
        elif password != confirm_password:
            msg = 'Passwords do not match!'
        elif len(password) < 6:
            msg = 'Password must be at least 6 characters long!'
        elif len(username) < 3:
            msg = 'Username must be at least 3 characters long!'
        else:
            try:
                conn = get_db_connection()
                cursor = conn.cursor(dictionary=True)
                
                # Check if username already exists
                cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
                account = cursor.fetchone()
                
                if account:
                    msg = 'Username already exists! Please choose another one.'
                else:
                    # Check if email already exists
                    cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
                    email_exists = cursor.fetchone()
                    
                    if email_exists:
                        msg = 'Email already registered! Please use another email.'
                    else:
                        # Insert new user
                        cursor.execute(
                            'INSERT INTO users (username, email, password) VALUES (%s, %s, %s)',
                            (username, email, password)
                        )
                        conn.commit()
                        cursor.close()
                        conn.close()
                        msg = 'Registration successful! You can now login.'
                        return render_template('login.html', msg=msg)
                
                cursor.close()
                conn.close()
                
            except mysql.connector.Error as err:
                msg = f"Database Error: {err}"
    
    return render_template('register.html', msg=msg)

@app.route('/dashboard')
def dashboard():
    if 'loggedin' in session:
        return render_template('dashboard.html', username=session['username'])
    return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'loggedin' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        if 'file' not in request.files: return redirect(request.url)
        file = request.files['file']
        if file.filename == '' or not file: return redirect(request.url)
        
        if allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO documents (user_id, filename, file_path, file_size) VALUES (%s, %s, %s, %s)',
                    (session['id'], filename, file_path, os.path.getsize(file_path))
                )
                conn.commit()
                session['current_document_id'] = cursor.lastrowid
                cursor.close()
                conn.close()
                return render_template('upload.html') 
            except mysql.connector.Error as err:
                return f"Database Error: {err}"
    return redirect(url_for('dashboard'))

# --- AI SUMMARY: NEW SPLIT LOGIC ---

# 1. Page Route: Just loads the loading screen
@app.route('/summary')
def summary():
    if 'loggedin' not in session: return redirect(url_for('login'))
    return render_template('summary.html')

# 2. API Route: Generates text in background
@app.route('/api/generate-summary')
def generate_summary_api():
    if 'loggedin' not in session: return jsonify({"error": "Unauthorized"}), 401
    
    doc_id = session.get('current_document_id')
    if not doc_id:
        return jsonify({"error": "No document found"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT file_path, filename FROM documents WHERE document_id = %s', (doc_id,))
    document = cursor.fetchone()
    cursor.close()
    conn.close()

    if not document: return jsonify({"error": "File not found"}), 404

    # Extract text
    raw_text = extract_text_from_file(document['file_path'])
    if len(raw_text) < 50:
        return jsonify({"error": "File is empty or too short."}), 400

    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        
        prompt = f""" 
        Analyze the following document thoroughly and create a summary.
        
        Please tell me:
        What is this document mainly about? (1 sentence). List the top 3-5 most important ideas and define them simply. Bullet points of other important facts mentioned.

        Here is the document text:
        {raw_text[:15000]} 
        """
        
        response = model.generate_content(prompt)
        ai_summary = response.text
        
        # Save raw text to session (so the "Save to Library" button works)
        session['current_summary'] = ai_summary
        
        # Convert to HTML (Markdown) for the frontend to display
        summary_html = markdown.markdown(ai_summary)
        
        return jsonify({"html": summary_html})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- AI QUIZ PAGE ---
@app.route('/quiz')
def quiz():
    if 'loggedin' in session: return render_template('quiz.html')
    return redirect(url_for('login'))

# --- API: GENERATE QUIZ DATA ---
@app.route('/api/generate-quiz')
def generate_quiz_api():
    if 'loggedin' not in session: 
        return jsonify({"error": "Unauthorized"}), 401
    
    doc_id = session.get('current_document_id')
    if not doc_id:
        return jsonify({"error": "No file uploaded"}), 400

    # 1. Fetch file path from DB
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT file_path FROM documents WHERE document_id = %s', (doc_id,))
    document = cursor.fetchone()
    cursor.close()
    conn.close()

    if not document: return jsonify({"error": "File not found in DB"}), 404

    # 2. Extract Text
    raw_text = extract_text_from_file(document['file_path'])
    if len(raw_text) < 50:
        return jsonify({"error": "File is empty or too short."}), 400

    # 3. Call AI
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        
        # Strict prompt to force JSON format
        prompt = f"""
        Create a multiple-choice quiz based on the text below.
        Return ONLY a raw JSON array of objects. Do not use Markdown formatting (no ```json).
        
        Generate 5 questions.
        Each object must have these exact keys:
        - "question": The question string
        - "options": An array of 4 strings (A, B, C, D)
        - "correct": The letter of the correct answer (e.g., "A", "B", "C", or "D")
        
        Text to analyze:
        {raw_text[:15000]}
        """
        
        response = model.generate_content(prompt)
        cleaned_response = response.text.strip()
        
        # Remove markdown code blocks if AI adds them despite instructions
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
            
        quiz_data = json.loads(cleaned_response)
        
        # Save to session so "Save to Library" works later
        session['current_quiz'] = json.dumps(quiz_data)
        
        return jsonify(quiz_data)

    except Exception as e:
        print(f"Quiz Generation Error: {e}")
        return jsonify({"error": str(e)}), 500


# --- LIBRARY & SAVING ---

@app.route('/mylibrary')
def mylibrary():
    if 'loggedin' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute('''
        SELECT * FROM library_content 
        WHERE user_id = %s 
        ORDER BY created_at DESC
    ''', (session['id'],))
    
    library_items = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('mylibrary.html', library_items=library_items)

# --- UPDATED SAVE CONTENT ---
@app.route('/save_content', methods=['POST'])
def save_content():
    if 'loggedin' not in session:
        return jsonify({'success': False, 'message': 'User not logged in'})

    data = request.get_json()
    content_type = data.get('type') # 'summary' or 'quiz'
    
    content_text = ""
    
    if content_type == 'summary':
        content_text = session.get('current_summary')
        
    elif content_type == 'quiz':
        # 1. Retrieve the original generated questions
        original_quiz_json = session.get('current_quiz')
        if not original_quiz_json:
             return jsonify({'success': False, 'message': 'Quiz data expired. Please regenerate.'})
        
        original_quiz = json.loads(original_quiz_json)
        
        # 2. Get user's results from the frontend request
        user_score = data.get('score')      # e.g., "3/5"
        user_answers = data.get('answers')  # e.g., ["A", "C", null, "B", "A"]
        
        # 3. Create a combined object to store everything
        saved_data = {
            "questions": original_quiz,
            "my_score": user_score,
            "my_answers": user_answers
        }
        
        # 4. Save as a JSON string
        content_text = json.dumps(saved_data)

    if not content_text:
        return jsonify({'success': False, 'message': 'No content to save!'})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        doc_id = session.get('current_document_id')
        cursor.execute('SELECT filename FROM documents WHERE document_id = %s', (doc_id,))
        doc_row = cursor.fetchone()
        filename = doc_row[0] if doc_row else "Untitled"
        
        title = f"{content_type.capitalize()} of {filename}"

        cursor.execute(
            'INSERT INTO library_content (user_id, document_id, title, content_type, output_text) VALUES (%s, %s, %s, %s, %s)',
            (session['id'], doc_id, title, content_type, content_text)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'new_filename': title})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# --- UPDATED VIEW CONTENT ---
@app.route('/view_content/<int:content_id>')
def view_content(content_id):
    if 'loggedin' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM library_content WHERE content_id = %s AND user_id = %s', (content_id, session['id']))
    content = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if content:
        # If it's a quiz, parse the JSON string back into a Python Dictionary
        if content['content_type'] == 'quiz':
            try:
                # We attach a new key 'quiz_data' to the content object
                content['quiz_data'] = json.loads(content['output_text'])
            except:
                content['quiz_data'] = None
                
        return render_template('view_content.html', content=content)
    else:
        return redirect(url_for('mylibrary'))

@app.route('/delete_content/<int:content_id>')
def delete_content(content_id):
    if 'loggedin' not in session: return redirect(url_for('login'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM library_content WHERE content_id = %s AND user_id = %s', (content_id, session['id']))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(e)
        
    return redirect(url_for('mylibrary'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)