import os
import uuid
import subprocess
import threading
import asyncio
import re
import requests
import json
import time
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'anisub-secret-key-2024')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = '/tmp/anisub_uploads'
app.config['OUTPUT_FOLDER'] = '/tmp/anisub_outputs'

# Ensure dirs exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

PASSWORD = "Ashraf0@#"

# Pyrogram credentials
API_ID = 35315188
API_HASH = "ccf9a114d0b6401bddec3f0aa243a029"
BOT_TOKEN = "8762932401:AAHoWrdYm8fhIt2e1RB-qktQhc5gFFa1ONQ"
CHANNEL_ID = -1003248434147

GEMINI_API_KEY = "AIzaSyAD9UcxHD474DyKE5iYmrNKLh5xInOodLk"

# In-memory task store
tasks = {}

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        pwd = request.form.get('password', '')
        if pwd == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            error = "ভুল পাসওয়ার্ড। আবার চেষ্টা করুন।"
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {
        'status': 'queued',
        'step': 'queued',
        'progress': 0,
        'logs': [],
        'error': None,
        'telegram_link': None
    }

    m3u8_url = request.form.get('m3u8_url', '').strip()
    subtitle_mode = request.form.get('subtitle_mode', 'file')
    subtitle_url = request.form.get('subtitle_url', '').strip()
    translate_source_url = request.form.get('translate_source_url', '').strip()
    translate_engine = request.form.get('translate_engine', 'google')
    subtitle_position = request.form.get('subtitle_position', 'bottom')
    font_size = request.form.get('font_size', '24')
    font_style = request.form.get('font_style', 'normal')
    font_color = request.form.get('font_color', 'white')
    background = request.form.get('background', 'none')
    video_title = request.form.get('video_title', 'Video').strip()
    caption = request.form.get('caption', '').strip()

    srt_file = request.files.get('srt_file')
    translate_srt_file = request.files.get('translate_srt_file')

    # Save uploaded files
    srt_path = None
    translate_srt_path = None

    if subtitle_mode == 'file' and srt_file and srt_file.filename:
        fname = secure_filename(srt_file.filename)
        srt_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{task_id}_sub.srt")
        srt_file.save(srt_path)

    if subtitle_mode == 'translate' and translate_srt_file and translate_srt_file.filename:
        fname = secure_filename(translate_srt_file.filename)
        translate_srt_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{task_id}_trans_src.srt")
        translate_srt_file.save(translate_srt_path)

    params = {
        'task_id': task_id,
        'm3u8_url': m3u8_url,
        'subtitle_mode': subtitle_mode,
        'subtitle_url': subtitle_url,
        'srt_path': srt_path,
        'translate_source_url': translate_source_url,
        'translate_srt_path': translate_srt_path,
        'translate_engine': translate_engine,
        'subtitle_position': subtitle_position,
        'font_size': font_size,
        'font_style': font_style,
        'font_color': font_color,
        'background': background,
        'video_title': video_title,
        'caption': caption,
    }

    t = threading.Thread(target=process_task, args=(params,), daemon=True)
    t.start()

    return jsonify({'task_id': task_id})

@app.route('/status/<task_id>', methods=['GET'])
@login_required
def status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(task)

def log_task(task_id, message):
    if task_id in tasks:
        tasks[task_id]['logs'].append(message)

def set_step(task_id, step, progress):
    if task_id in tasks:
        tasks[task_id]['step'] = step
        tasks[task_id]['progress'] = progress
        tasks[task_id]['status'] = 'running'

def process_task(params):
    task_id = params['task_id']
    upload_dir = app.config['UPLOAD_FOLDER']
    output_dir = app.config['OUTPUT_FOLDER']

    raw_video = os.path.join(upload_dir, f"{task_id}_raw.mp4")
    final_video = os.path.join(output_dir, f"{task_id}_final.mp4")
    srt_path = params.get('srt_path')

    try:
        # ---- Step 1: Download video ----
        set_step(task_id, 'downloading', 5)
        log_task(task_id, "⏳ ভিডিও ডাউনলোড শুরু হচ্ছে...")

        m3u8_url = params['m3u8_url']
        if not m3u8_url:
            raise ValueError("M3U8 URL দেওয়া হয়নি")

        result = subprocess.run([
            'ffmpeg', '-y',
            '-user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            '-headers', 'Referer: https://seehd24.rpmvip.com/\r\nOrigin: https://seehd24.rpmvip.com',
            '-i', m3u8_url,
            '-c', 'copy',
            raw_video
        ], capture_output=True, text=True, timeout=3600)

        if result.returncode != 0:
            raise RuntimeError(f"ভিডিও ডাউনলোড ব্যর্থ হয়েছে:\n{result.stderr[-500:]}")

        log_task(task_id, "✅ ভিডিও ডাউনলোড সম্পন্ন হয়েছে।")
        set_step(task_id, 'downloading', 30)

        # ---- Step 2: Subtitle preparation ----
        subtitle_mode = params['subtitle_mode']
        set_step(task_id, 'translating', 35)

        if subtitle_mode == 'url':
            log_task(task_id, "📥 URL থেকে সাবটাইটেল ডাউনলোড হচ্ছে...")
            srt_url = params['subtitle_url']
            if not srt_url:
                raise ValueError("সাবটাইটেল URL দেওয়া হয়নি")
            r = requests.get(srt_url, timeout=60)
            r.raise_for_status()
            srt_path = os.path.join(upload_dir, f"{task_id}_sub.srt")
            with open(srt_path, 'wb') as f:
                f.write(r.content)
            log_task(task_id, "✅ সাবটাইটেল ডাউনলোড সম্পন্ন।")

        elif subtitle_mode == 'translate':
            log_task(task_id, "🌐 সাবটাইটেল অনুবাদ হচ্ছে...")
            src_srt = params.get('translate_srt_path')

            if not src_srt and params.get('translate_source_url'):
                r = requests.get(params['translate_source_url'], timeout=60)
                r.raise_for_status()
                src_srt = os.path.join(upload_dir, f"{task_id}_trans_src.srt")
                with open(src_srt, 'wb') as f:
                    f.write(r.content)

            if not src_srt or not os.path.exists(src_srt):
                raise ValueError("অনুবাদের জন্য সাবটাইটেল ফাইল পাওয়া যায়নি")

            engine = params.get('translate_engine', 'google')
            srt_path = os.path.join(upload_dir, f"{task_id}_sub.srt")
            translate_srt(src_srt, srt_path, engine, task_id)
            log_task(task_id, "✅ সাবটাইটেল অনুবাদ সম্পন্ন।")

        elif subtitle_mode == 'file':
            if not srt_path or not os.path.exists(srt_path):
                raise ValueError("সাবটাইটেল ফাইল আপলোড করা হয়নি")
            log_task(task_id, "✅ সাবটাইটেল ফাইল প্রস্তুত।")

        set_step(task_id, 'translating', 50)

        # ---- Step 3: Burn subtitles ----
        set_step(task_id, 'processing', 55)
        log_task(task_id, "🎬 সাবটাইটেল মার্জ হচ্ছে...")

        force_style = build_force_style(params)
        srt_path_escaped = srt_path.replace('\\', '/').replace(':', '\\:')

        burn_result = subprocess.run([
            'ffmpeg', '-y',
            '-i', raw_video,
            '-vf', f"subtitles='{srt_path_escaped}':force_style='{force_style}'",
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '28',
            '-c:a', 'copy',
            '-threads', '0',
            final_video
        ], capture_output=True, text=True, timeout=3600)

        if burn_result.returncode != 0:
            raise RuntimeError(f"সাবটাইটেল মার্জ ব্যর্থ হয়েছে:\n{burn_result.stderr[-500:]}")

        log_task(task_id, "✅ সাবটাইটেল মার্জ সম্পন্ন।")
        set_step(task_id, 'processing', 75)

        # ---- Step 4: Upload to Telegram ----
        set_step(task_id, 'uploading', 80)
        log_task(task_id, "📤 Telegram এ আপলোড হচ্ছে...")

        video_title = params.get('video_title', 'Video')
        caption_text = params.get('caption', '')
        full_caption = f"**{video_title}**"
        if caption_text:
            full_caption += f"\n\n{caption_text}"

        msg_id = upload_to_telegram_sync(final_video, full_caption, task_id)

        tg_link = None
        if msg_id:
            channel_username = str(CHANNEL_ID).replace('-100', '')
            tg_link = f"https://t.me/c/{channel_username}/{msg_id}"

        log_task(task_id, "✅ Telegram আপলোড সম্পন্ন!")
        tasks[task_id]['telegram_link'] = tg_link
        tasks[task_id]['status'] = 'done'
        tasks[task_id]['step'] = 'done'
        tasks[task_id]['progress'] = 100

    except Exception as e:
        tasks[task_id]['status'] = 'error'
        tasks[task_id]['step'] = 'error'
        tasks[task_id]['error'] = str(e)
        log_task(task_id, f"❌ ত্রুটি: {str(e)}")
    finally:
        # Cleanup
        for path in [raw_video, srt_path]:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


def build_force_style(params):
    position = params.get('subtitle_position', 'bottom')
    font_size = params.get('font_size', '24')
    font_style = params.get('font_style', 'normal')
    font_color = params.get('font_color', 'white')
    background = params.get('background', 'none')

    color_map = {
        'white': '&H00FFFFFF',
        'yellow': '&H0000FFFF',
        'cyan': '&H00FFFF00',
    }
    primary_color = color_map.get(font_color, '&H00FFFFFF')

    alignment_map = {
        'top': '8',
        'middle': '5',
        'bottom': '2',
    }
    alignment = alignment_map.get(position, '2')

    bold = '1' if font_style == 'bold' else '0'
    italic = '1' if font_style == 'italic' else '0'

    back_colour = '&H00000000'
    border_style = '1'
    outline = '1'
    shadow = '0'
    back_alpha = '00'

    if background == 'semi':
        back_colour = '&H80000000'
        border_style = '3'
        outline = '0'
    elif background == 'black':
        back_colour = '&HFF000000'
        border_style = '3'
        outline = '0'

    style = (
        f"FontName=Noto Sans Bengali,"
        f"FontSize={font_size},"
        f"PrimaryColour={primary_color},"
        f"Bold={bold},"
        f"Italic={italic},"
        f"Alignment={alignment},"
        f"BackColour={back_colour},"
        f"BorderStyle={border_style},"
        f"Outline={outline},"
        f"Shadow={shadow}"
    )
    return style


def translate_srt(src_path, dest_path, engine, task_id):
    with open(src_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    blocks = re.split(r'\n\n+', content.strip())
    translated_blocks = []

    for i, block in enumerate(blocks):
        lines = block.strip().split('\n')
        if len(lines) < 3:
            translated_blocks.append(block)
            continue

        index_line = lines[0]
        time_line = lines[1]
        text_lines = lines[2:]
        text = ' '.join(text_lines)

        try:
            if engine == 'google':
                translated = google_translate(text, 'bn')
            elif engine == 'deepl':
                translated = deepl_translate(text, 'bn')
            elif engine == 'gemini':
                translated = gemini_translate(text, 'bn')
            else:
                translated = text
        except Exception as e:
            log_task(task_id, f"⚠️ Block {i+1} অনুবাদ ব্যর্থ: {str(e)[:80]}")
            translated = text

        translated_blocks.append(f"{index_line}\n{time_line}\n{translated}")

        if (i + 1) % 20 == 0:
            log_task(task_id, f"🌐 {i+1}/{len(blocks)} লাইন অনুবাদ হয়েছে...")

    with open(dest_path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(translated_blocks))


def google_translate(text, target_lang):
    from deep_translator import GoogleTranslator
    return GoogleTranslator(source='auto', target=target_lang).translate(text)


def deepl_translate(text, target_lang):
    from deep_translator import DeeplTranslator
    return DeeplTranslator(source='auto', target=target_lang).translate(text)


def gemini_translate(text, target_lang):
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"Translate the following subtitle text to Bengali (bn). Return ONLY the translated text, nothing else:\n\n{text}"
    response = model.generate_content(prompt)
    return response.text.strip()


def upload_to_telegram_sync(file_path, caption, task_id):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(_upload_telegram(file_path, caption, task_id))
        return result
    finally:
        loop.close()


async def _upload_telegram(file_path, caption, task_id):
    from pyrogram import Client
    file_size = os.path.getsize(file_path)
    uploaded_bytes = [0]
    last_log_pct = [0]

    def progress(current, total):
        uploaded_bytes[0] = current
        pct = int((current / total) * 100) if total else 0
        task_progress = 80 + int(pct * 0.18)
        tasks[task_id]['progress'] = min(task_progress, 98)
        if pct - last_log_pct[0] >= 10:
            last_log_pct[0] = pct
            log_task(task_id, f"📤 আপলোড: {pct}% ({current // (1024*1024)} MB / {total // (1024*1024)} MB)")

    async with Client(
        "anisub_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        in_memory=True
    ) as client:
        msg = await client.send_video(
            chat_id=CHANNEL_ID,
            video=file_path,
            caption=caption,
            supports_streaming=True,
            progress=progress,
        )
        return msg.id


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
