"""
STT（語音轉文字）
-----------------
- faster-whisper 選裝檢查（沒裝時 STT 停用）、_whisper_model、STT_AVAILABLE、_load_whisper_model（啟動時載入模型）
- pcm_to_wav_bytes、_google_translate、transcribe_bilingual（PTT 上傳用，中英雙語）、transcribe_pcm_bytes（MQTT PTT 音訊用）

從 main.py 原樣搬出兩段：49–74 行（選裝檢查與模型載入）、353–405 行（STT 函式）。
唯一新增的是最下面的 is_available()：STT_AVAILABLE 要等啟動後 _load_whisper_model() 用 global 改成 True，
其他模組 from features.stt import STT_AVAILABLE 只會拿到匯入當下的 False，所以 main.py 改用 stt.is_available() 在當下讀取。
這支檔案沒有路由（/api/social/stt_status 還在 main.py，之後跟 Social 一起拆），也不 import main。
"""
import asyncio, io, json, wave
import urllib.request
import urllib.parse

# ====== STT (語音轉文字) 相依套件（選裝）======
try:
    from faster_whisper import WhisperModel as _WhisperModelClass
    _WHISPER_IMPORT_OK = True
except ImportError:
    _WhisperModelClass = None
    _WHISPER_IMPORT_OK = False

_whisper_model = None
STT_AVAILABLE  = False

async def _load_whisper_model():
    global _whisper_model, STT_AVAILABLE
    if not _WHISPER_IMPORT_OK:
        print("[STT] faster-whisper not installed, STT disabled")
        return
    try:
        import concurrent.futures
        loop = asyncio.get_running_loop()
        def _load():
            return _WhisperModelClass("base", device="cpu", compute_type="int8")
        _whisper_model = await loop.run_in_executor(None, _load)
        STT_AVAILABLE = True
        print("[STT] faster-whisper model loaded, STT enabled")
    except Exception as _e:
        print(f"[STT] model load failed ({_e}), STT disabled")

# ====== STT 函式 ======
def pcm_to_wav_bytes(pcm_data: bytes, sample_rate=8000, channels=1, sampwidth=2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(channels); wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate); wf.writeframes(pcm_data)
    return buf.getvalue()

def _google_translate(text: str, target_lang: str) -> str:
    if not text.strip(): return ""
    try:
        params = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": target_lang, "dt": "t", "q": text})
        req = urllib.request.Request(
            f"https://translate.googleapis.com/translate_a/single?{params}",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return "".join(item[0] for item in data[0] if item[0]).strip()
    except Exception as e:
        print(f"[STT] Translation error ({target_lang}): {e}")
        return ""

def transcribe_bilingual(audio_path: str) -> tuple:
    if not STT_AVAILABLE or not _whisper_model: return ("", "")
    try:
        segments, info = _whisper_model.transcribe(audio_path, language=None, beam_size=5)
        original_text = "".join(s.text for s in segments).strip()
        detected_lang = (info.language or "").lower()
        if detected_lang == "en":
            text_en = original_text
        else:
            en_segs, _ = _whisper_model.transcribe(audio_path, task="translate", beam_size=5)
            text_en = "".join(s.text for s in en_segs).strip()
        if detected_lang in ("zh", "yue"):
            text_zh = original_text
        else:
            text_zh = _google_translate(text_en or original_text, "zh-TW")
        return (text_zh, text_en)
    except Exception as e:
        print(f"[STT] 雙語辨識錯誤: {e}")
        return ("", "")

def transcribe_pcm_bytes(pcm_data: bytes) -> str:
    if not STT_AVAILABLE or not _whisper_model or len(pcm_data) < 1600: return ""
    try:
        wav_bytes = pcm_to_wav_bytes(pcm_data)
        buf = io.BytesIO(wav_bytes)
        segments, _ = _whisper_model.transcribe(buf, language=None, beam_size=5)
        return "".join(s.text for s in segments).strip()
    except Exception as e:
        print(f"[STT] PCM 辨識錯誤: {e}")
        return ""

# [拆分 stt.py 新增] STT_AVAILABLE 在啟動後才由 _load_whisper_model() 用 global 改成 True，
# 其他模組要用這個函式在當下讀取，不要 from features.stt import STT_AVAILABLE（會一直拿到 False）
def is_available():
    return STT_AVAILABLE
