import re
import os
import time
import tempfile
import subprocess
from pathlib import Path

# ── Detección de plataforma ───────────────────────────────────────────────────

PLATFORM_PATTERNS = {
    "youtube": [
        r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})"
    ],
    "tiktok": [
        r"tiktok\.com/@[^/]+/video/(\d+)",
        r"(?:vm|vt)\.tiktok\.com/([A-Za-z0-9]+)",
        r"tiktok\.com/t/([A-Za-z0-9]+)",
    ],
    "twitter": [
        r"(?:twitter|x)\.com/\w+/status/(\d+)"
    ],
    "instagram": [
        r"instagram\.com/(?:reel|p|tv)/([A-Za-z0-9_-]+)"
    ],
}

def detect_platform(url: str) -> tuple[str, str]:
    for platform, patterns in PLATFORM_PATTERNS.items():
        for pattern in patterns:
            m = re.search(pattern, url)
            if m:
                return platform, m.group(1)
    return "generic", url.split("/")[-1] or "video"


# ── YouTube Transcript API ────────────────────────────────────────────────────

def _youtube_api(video_id: str, retries: int = 3) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None

    for attempt in range(retries):
        try:
            api = YouTubeTranscriptApi()
            # Intentar español primero, luego inglés, luego cualquiera
            for langs in [["es"], ["en"], None]:
                try:
                    kwargs = {"languages": langs} if langs else {}
                    data = api.fetch(video_id, **kwargs).to_raw_data()
                    return " ".join(t["text"] for t in data)
                except Exception:
                    continue
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
    return None


# ── Descarga con yt-dlp ───────────────────────────────────────────────────────

def _download_audio(url: str, out_path: str) -> str:
    """Descarga solo el audio del video. Retorna la ruta del archivo."""
    cmd = [
        "yt-dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio/best",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",          # balance calidad/tamaño
        "--no-playlist",
        "-o", out_path,
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp falló: {result.stderr[:300]}")

    # yt-dlp puede cambiar la extensión
    path = Path(out_path)
    if not path.exists():
        candidates = list(path.parent.glob(f"{path.stem}.*"))
        if not candidates:
            raise FileNotFoundError("No se encontró el archivo descargado")
        return str(candidates[0])
    return out_path


# ── Groq Whisper ─────────────────────────────────────────────────────────────

def _groq_transcribe(audio_path: str, language: str | None = None) -> str:
    from groq import Groq
    import streamlit as st

    api_key = st.secrets.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("Falta GROQ_API_KEY en secrets o variables de entorno")

    client = Groq(api_key=api_key)

    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=f,
            response_format="text",
            language=language,          # None = autodetectar
        )

    # Groq devuelve string directamente con response_format="text"
    return response if isinstance(response, str) else response.text


# ── Función principal ─────────────────────────────────────────────────────────

def transcribe_url(url: str, language: str | None = None) -> dict:
    """
    Transcribe un video desde su URL.

    Returns:
        {
            "success": bool,
            "text": str | None,
            "platform": str,
            "method": str,          # "youtube_api" | "groq_whisper"
            "error": str | None,
        }
    """
    platform, video_id = detect_platform(url)

    # ── 1. YouTube: intentar API nativa primero ───────────────────────────────
    if platform == "youtube":
        text = _youtube_api(video_id)
        if text:
            return {
                "success": True,
                "text": text,
                "platform": platform,
                "method": "youtube_api",
                "error": None,
            }

    # ── 2. Fallback: descargar audio + Groq Whisper ───────────────────────────
    try:
        with tempfile.TemporaryDirectory() as tmp:
            audio_out = os.path.join(tmp, f"{video_id}.mp3")
            audio_path = _download_audio(url, audio_out)
            text = _groq_transcribe(audio_path, language)

        return {
            "success": True,
            "text": text.strip(),
            "platform": platform,
            "method": "groq_whisper",
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "text": None,
            "platform": platform,
            "method": "groq_whisper",
            "error": str(e),
        }
