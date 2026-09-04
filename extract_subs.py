import os
import re
import json
import subprocess
from groq import Groq

WORK_DIR = os.environ.get("GDRIVE_DIR", os.path.expanduser("~/gdrive"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

ALLOWED_LANGS = {
    "ukr": ["ukr", "uk", "ua", "ukrainian"],
    "rus": ["rus", "ru", "russian"],
    "eng": ["eng", "en", "english"]
}

def srt_to_vtt(srt_path, vtt_path):
    try:
        with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        body = re.sub(r'(\d{2}:\d{2}:\d{2}),(\d{3})', r'\1.\2', content)
        body = re.sub(r'\{.*?\}', '', body)
        with open(vtt_path, "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n" + body.strip() + "\n")
        print(f"  ✓ Створено VTT: {os.path.basename(vtt_path)}")
    except Exception as e:
        print(f"  ⚠️ Помилка створення VTT: {e}")

def detect_language(track_props):
    lang = track_props.get("language", "").lower()
    name = track_props.get("track_name", "").lower()
    for canon, aliases in ALLOWED_LANGS.items():
        if lang in aliases or any(a in name for a in aliases):
            return canon
    return None

def is_text_subtitle(codec_id):
    codec = (codec_id or "").lower()
    return any(t in codec for t in ["text", "subrip", "srt", "ass", "ssa", "vtt"])

def translate_lines_to_ukr(lines):
    if not lines or not groq_client:
        return lines
    prompt = (
        "Translate these movie subtitle lines into natural Ukrainian. "
        "Keep speaker labels and timing intact. "
        "Return ONLY a JSON array of strings corresponding 1:1 to inputs.\n"
        f"Input:\n{json.dumps(lines, ensure_ascii=False)}"
    )
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        data = json.loads(resp.choices[0].message.content)
        for k in data:
            if isinstance(data[k], list):
                return data[k]
        return lines
    except Exception as e:
        print(f"  ⚠️ Помилка Groq API: {e}")
        return lines

def translate_srt_file(src_srt, dest_srt):
    import pysrt
    subs = pysrt.open(src_srt, encoding="utf-8", errors="ignore")
    chunk_size = 50
    for i in range(0, len(subs), chunk_size):
        chunk = subs[i:i + chunk_size]
        raw_text = [s.text for s in chunk]
        translated = translate_lines_to_ukr(raw_text)
        for s, t in zip(chunk, translated):
            s.text = t
    subs.save(dest_srt, encoding="utf-8")
    print(f"  ✓ Створено переклад UKR: {os.path.basename(dest_srt)}")

def process_file(vid_path, root, vid):
    base_name = os.path.splitext(vid)[0]

    ukr_srt = os.path.join(root, f"{base_name}.ukr.srt")
    rus_srt = os.path.join(root, f"{base_name}.rus.srt")
    eng_srt = os.path.join(root, f"{base_name}.eng.srt")

    has_ukr = os.path.exists(ukr_srt)
    has_rus = os.path.exists(rus_srt)
    has_eng = os.path.exists(eng_srt)

    cmd_info = f'mkvmerge -J "{vid_path}"'
    res = subprocess.run(cmd_info, shell=True, stdout=subprocess.PIPE, text=True)
    if res.returncode != 0:
        print(f"❌ Не вдалося прочитати дані файлу {vid}")
        return

    try:
        tracks = json.loads(res.stdout).get("tracks", [])
    except Exception:
        return

    sub_tracks = [
        t for t in tracks 
        if t.get("type") == "subtitles" and is_text_subtitle(t.get("codec"))
    ]

    if not sub_tracks:
        print(f"ℹ️ У {vid} немає текстових субтитрів.")
        return

    print(f"🎬 Знайдено доріжки у: {vid}")

    found_tracks = {"ukr": None, "rus": None, "eng": None}
    other_sub_ids = []

    for st in sub_tracks:
        props = st.get("properties", {})
        track_id = st.get("id")
        lang = detect_language(props)
        name = props.get("track_name", "").lower()
        is_sdh = "sdh" in name or "cc" in name

        if lang:
            if found_tracks[lang] is None or (not is_sdh and "sdh" in str(found_tracks[lang])):
                found_tracks[lang] = track_id
        else:
            other_sub_ids.append(track_id)

    # 1. Витяг UKR
    if found_tracks["ukr"] is not None and not has_ukr:
        print(f"  📥 Витяг UKR ID {found_tracks['ukr']}...")
        subprocess.run(f'mkvextract tracks "{vid_path}" {found_tracks["ukr"]}:"{ukr_srt}"', shell=True)
        srt_to_vtt(ukr_srt, os.path.join(root, f"{base_name}.ukr.vtt"))
        has_ukr = True

    # 2. Витяг RUS
    if found_tracks["rus"] is not None and not has_rus:
        print(f"  📥 Витяг RUS ID {found_tracks['rus']}...")
        subprocess.run(f'mkvextract tracks "{vid_path}" {found_tracks["rus"]}:"{rus_srt}"', shell=True)
        srt_to_vtt(rus_srt, os.path.join(root, f"{base_name}.rus.vtt"))
        has_rus = True

    # 3. Витяг ENG
    if found_tracks["eng"] is not None and not has_eng:
        print(f"  📥 Витяг ENG ID {found_tracks['eng']}...")
        subprocess.run(f'mkvextract tracks "{vid_path}" {found_tracks["eng"]}:"{eng_srt}"', shell=True)
        srt_to_vtt(eng_srt, os.path.join(root, f"{base_name}.eng.vtt"))
        has_eng = True

    # 4. Переклад на UKR за відсутності UKR та RUS
    if not has_ukr and not has_rus:
        source_sub = None
        if os.path.exists(eng_srt):
            source_sub = eng_srt
        elif other_sub_ids:
            fallback_path = os.path.join(root, f"{base_name}.fallback.srt")
            subprocess.run(f'mkvextract tracks "{vid_path}" {other_sub_ids[0]}:"{fallback_path}"', shell=True)
            source_sub = fallback_path

        if source_sub and os.path.exists(source_sub):
            print(f"  🌐 Переклад субтитрів на UKR...")
            translate_srt_file(source_sub, ukr_srt)
            srt_to_vtt(ukr_srt, os.path.join(root, f"{base_name}.ukr.vtt"))
            if "fallback" in source_sub and os.path.exists(source_sub):
                os.remove(source_sub)

def main():
    if not os.path.exists(WORK_DIR):
        print(f"❌ Директорію {WORK_DIR} не знайдено!")
        return

    print(f"🔍 Сканування директорії: {WORK_DIR}")
    found_videos = 0

    for root, _, files in os.walk(WORK_DIR):
        for vid in files:
            if vid.lower().endswith(('.mkv', '.mp4', '.m4v')):
                found_videos += 1
                vid_path = os.path.join(root, vid)
                process_file(vid_path, root, vid)

    print(f"✅ Перевірено відеофайлів: {found_videos}")

if __name__ == "__main__":
    main()