import re
import os
import time
import shutil
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


# ── Extracción de audio desde archivo de video ────────────────────────────────

def _require_ffmpeg() -> str:
    """Retorna la ruta de ffmpeg o lanza un error claro si no está disponible."""
    path = shutil.which("ffmpeg")
    if path is None:
        raise RuntimeError(
            "ffmpeg no encontrado en PATH. "
            "Instalalo con: scoop install ffmpeg  (o choco install ffmpeg) "
            "y reiniciá el terminal."
        )
    return path


def _extract_audio_from_video(video_path: str, out_path: str) -> None:
    """Extrae audio de un archivo de video usando ffmpeg (64kbps mono 16kHz)."""
    cmd = [
        _require_ffmpeg(), "-i", video_path,
        "-vn",                   # sin pista de video
        "-acodec", "libmp3lame",
        "-ab", "64k",            # 64kbps → ~28 MB/hora, buena calidad para voz
        "-ar", "16000",          # 16 kHz: suficiente para transcripción
        "-ac", "1",              # mono
        "-y",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg falló al extraer audio: {result.stderr[:400]}")


def _audio_duration_secs(audio_path: str) -> float | None:
    """Retorna la duración en segundos usando ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    cmd = [
        ffprobe, "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _split_audio(audio_path: str, tmp_dir: str, chunk_minutes: int = 20) -> list[str]:
    """
    Divide el audio en chunks de `chunk_minutes` minutos usando ffmpeg.
    Retorna la lista de rutas de los chunks generados.
    """
    duration = _audio_duration_secs(audio_path)
    if duration is None:
        return [audio_path]  # si no podemos medir, intentamos sin dividir

    chunk_secs = chunk_minutes * 60
    chunks: list[str] = []
    start = 0.0
    i = 0

    while start < duration:
        chunk_path = os.path.join(tmp_dir, f"chunk_{i:03d}.mp3")
        cmd = [
            "ffmpeg",
            "-ss", str(start),
            "-t", str(chunk_secs),
            "-i", audio_path,
            "-c", "copy",
            "-y",
            chunk_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and Path(chunk_path).exists():
            chunks.append(chunk_path)
        start += chunk_secs
        i += 1

    return chunks if chunks else [audio_path]


# ── Transcripción desde archivo local ────────────────────────────────────────

GROQ_MAX_MB = 24  # margen de seguridad bajo el límite de 25 MB de Groq


def _transcribe_video_path(video_path: str, language: str | None = None) -> str:
    """Extrae audio de un video en disco y lo transcribe. Hace chunking si es necesario."""
    with tempfile.TemporaryDirectory() as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        _extract_audio_from_video(video_path, audio_path)

        size_mb = Path(audio_path).stat().st_size / (1024 * 1024)
        if size_mb <= GROQ_MAX_MB:
            return _groq_transcribe(audio_path, language)

        # Audio grande → dividir en chunks de 20 min y transcribir cada uno
        chunks = _split_audio(audio_path, tmp, chunk_minutes=20)
        return " ".join(_groq_transcribe(c, language) for c in chunks)


def transcribe_file(file_obj, filename: str, language: str | None = None) -> dict:
    """
    Transcribe un archivo de video subido desde el navegador (UploadedFile de Streamlit).
    Usa shutil.copyfileobj para no duplicar el buffer en memoria.
    Límite práctico: ~500 MB (depende de la RAM disponible).
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, filename)
            with open(video_path, "wb") as f:
                shutil.copyfileobj(file_obj, f, length=8 * 1024 * 1024)  # 8 MB por chunk
            text = _transcribe_video_path(video_path, language)

        return {"success": True, "text": text.strip(), "platform": "local",
                "method": "groq_whisper", "error": None}

    except Exception as e:
        return {"success": False, "text": None, "platform": "local",
                "method": "groq_whisper", "error": str(e)}


def transcribe_local_path(path: str, language: str | None = None) -> dict:
    """
    Transcribe un video desde una ruta en disco (sin subirlo).
    Ideal para archivos grandes (2 GB+): ffmpeg lee directo desde disco,
    sin pasar el video por memoria.
    """
    p = Path(path)
    if not p.exists():
        return {"success": False, "text": None, "platform": "local",
                "method": "groq_whisper", "error": f"Archivo no encontrado: {path}"}
    if not p.is_file():
        return {"success": False, "text": None, "platform": "local",
                "method": "groq_whisper", "error": f"La ruta no es un archivo: {path}"}

    try:
        text = _transcribe_video_path(str(p), language)
        return {"success": True, "text": text.strip(), "platform": "local",
                "method": "groq_whisper", "error": None}

    except Exception as e:
        return {"success": False, "text": None, "platform": "local",
                "method": "groq_whisper", "error": str(e)}


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
