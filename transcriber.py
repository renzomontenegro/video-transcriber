import re
import os
import sys
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


# ── Cookies para yt-dlp ───────────────────────────────────────────────────────

def _read_secret(name: str) -> str | None:
    """Lee una config desde variable de entorno o st.secrets (en ese orden)."""
    val = os.environ.get(name)
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(name)
    except Exception:
        return None


def _cookie_args(work_dir: str) -> list[str]:
    """
    Arma los argumentos de cookies para yt-dlp según el entorno.

    Prioridad:
    1. YTDLP_COOKIES_FILE (secret o env): ruta a un cookies.txt ya exportado
       (formato Netscape). Es la opción más confiable en LOCAL Windows, porque
       Chrome/Edge nuevos usan App-Bound Encryption y --cookies-from-browser falla.
    2. YTDLP_COOKIES / IG_COOKIES (secret o env): contenido de un cookies.txt en
       formato Netscape. Se vuelca a un archivo temporal y se pasa con --cookies.
       Es la opción para DEPLOY en servidor (Streamlit Cloud), donde no hay browser.
    3. YTDLP_COOKIES_FROM_BROWSER (secret o env): nombre del navegador
       (chrome/edge/firefox/brave). yt-dlp lee las cookies del browser logueado;
       puede fallar en Windows reciente (ver punto 1).

    Retorna [] si no hay nada configurado.
    """
    cookie_path = _read_secret("YTDLP_COOKIES_FILE")
    if cookie_path and Path(cookie_path).is_file():
        return ["--cookies", cookie_path]

    raw = _read_secret("YTDLP_COOKIES") or _read_secret("IG_COOKIES")
    if raw:
        cookie_file = os.path.join(work_dir, "cookies.txt")
        with open(cookie_file, "w", encoding="utf-8") as f:
            f.write(raw)
        return ["--cookies", cookie_file]

    browser = _read_secret("YTDLP_COOKIES_FROM_BROWSER")
    if browser:
        return ["--cookies-from-browser", browser.strip()]

    return []


# ── Instagram: descarga directa sin login ─────────────────────────────────────
#
# Instagram bloquea su API para usuarios sin sesión, pero el reproductor sigue
# cargando el video por detrás del modal de login. La página de "embed captioned"
# expone la URL firmada del mp4 en su HTML (dentro de un JSON doble-escapado),
# accesible sin cookies. Replicamos eso: bajamos el embed con impersonation de
# Chrome, extraemos el mp4 y sacamos el audio con ffmpeg. Es más robusto que las
# cookies (que caducan y sufren rate-limit), así que lo intentamos PRIMERO.

def _instagram_media_url(shortcode: str) -> str | None:
    """Devuelve la URL directa del mp4 de un reel/post IG, o None si no la halla."""
    from curl_cffi import requests as cffi

    # /reel/ y /p/ comparten el mismo embed; probamos ambos por las dudas.
    embeds = [
        f"https://www.instagram.com/reel/{shortcode}/embed/captioned/",
        f"https://www.instagram.com/p/{shortcode}/embed/captioned/",
    ]
    for embed in embeds:
        try:
            r = cffi.get(embed, impersonate="chrome", timeout=20)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        html = r.text
        for m in re.finditer(r"\.mp4", html):
            start = html.rfind("https", max(0, m.start() - 1500), m.start())
            if start == -1:
                continue
            mm = re.match(r'(https.*?)\\?"', html[start:start + 1600])
            if not mm:
                continue
            # El JSON viene doble-escapado: \\/ → /  y  \\u0026 → &
            u = re.sub(r"\\+u0026", "&", mm.group(1))
            u = re.sub(r"\\+", "", u)
            if u.startswith("http"):
                return u
    return None


def _download_instagram_audio(url: str, out_path: str) -> str | None:
    """Baja el reel vía embed (sin login) y devuelve el mp3. None si no se pudo."""
    _, shortcode = detect_platform(url)
    media_url = _instagram_media_url(shortcode)
    if not media_url:
        return None

    from curl_cffi import requests as cffi
    try:
        resp = cffi.get(media_url, impersonate="chrome", timeout=120)
    except Exception:
        return None
    if resp.status_code != 200 or "video" not in (resp.headers.get("content-type") or ""):
        return None

    video_path = str(Path(out_path).with_suffix(".ig.mp4"))
    with open(video_path, "wb") as f:
        f.write(resp.content)

    # Reutilizamos el extractor de audio (mp3 64k mono 16k, ideal para Whisper).
    audio_path = str(Path(out_path).with_suffix(".mp3"))
    _extract_audio_from_video(video_path, audio_path)
    return audio_path


# ── Descarga con yt-dlp ───────────────────────────────────────────────────────

def _download_audio(url: str, out_path: str) -> str:
    """Descarga solo el audio del video. Retorna la ruta del archivo."""
    is_tiktok = "tiktok.com" in url
    is_instagram = "instagram.com" in url

    # Instagram: probamos primero el bypass directo (sin login). Si falla,
    # caemos a yt-dlp con cookies (ver _cookie_args).
    if is_instagram:
        try:
            direct = _download_instagram_audio(url, out_path)
            if direct:
                return direct
        except Exception:
            pass  # cualquier problema → fallback a yt-dlp

    if is_tiktok:
        # TikTok no expone formatos de solo-audio y sus variantes h265 (bytevc1)
        # bajan SIN pista de audio → forzamos h264, que siempre trae aac.
        fmt = "best[vcodec^=h264][acodec!=none]/best"
    else:
        # YouTube/Twitter/Instagram: el stream de solo-audio es lo más liviano.
        fmt = "bestaudio[ext=m4a]/bestaudio/best"

    # Invocamos yt-dlp como módulo del Python actual (no el ejecutable del PATH,
    # que puede ser una instalación vieja sin soporte de --impersonate).
    cmd = [sys.executable, "-m", "yt_dlp", "-f", fmt]
    if is_tiktok or is_instagram:
        # TikTok exige TLS impersonation; en Instagram ayuda a no parecer un bot
        # (requiere curl_cffi instalado, ya está en requirements).
        cmd += ["--impersonate", "chrome"]

    # Instagram bloquea casi todos los reels para usuarios sin login: yt-dlp
    # responde "empty media response". Las cookies de una sesión logueada lo
    # resuelven (ver _cookie_args). Sin cookies, abajo damos un error claro.
    cookie_args = _cookie_args(str(Path(out_path).parent))
    cmd += cookie_args

    cmd += [
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",          # balance calidad/tamaño
        "--no-playlist",
        "-o", out_path,
        url,
    ]

    # El challenge JS de TikTok falla con "universal data for rehydration"
    # cuando rate-limitea por requests muy seguidos. No es error de red, así que
    # --extractor-retries no lo cubre: reintentamos el proceso con backoff
    # creciente (los reintentos rápidos empeoran el bloqueo).
    attempts = 4 if is_tiktok else 1
    result = None
    for attempt in range(attempts):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            break
        if attempt < attempts - 1 and "rehydration" in (result.stderr or ""):
            time.sleep(15 * (attempt + 1))   # 15s, 30s, 45s
            continue
        break
    if result.returncode != 0:
        stderr = result.stderr or ""
        # Caso típico de Instagram sin sesión: damos una instrucción accionable
        # en vez del traceback crudo de yt-dlp.
        if is_instagram and ("empty media response" in stderr or "login" in stderr.lower()) \
                and not cookie_args:
            raise RuntimeError(
                "Instagram requiere sesión iniciada para este reel. "
                "Exportá un cookies.txt de instagram.com (extensión 'Get cookies.txt LOCALLY') "
                "y seteá YTDLP_COOKIES_FILE con su ruta (local), o pegá su contenido en el "
                "secret YTDLP_COOKIES (deploy). Ver README."
            )
        raise RuntimeError(f"yt-dlp falló: {stderr[:300]}")

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
