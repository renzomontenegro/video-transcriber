Video Transcriber

App Streamlit para transcribir videos de YouTube, TikTok, Twitter/X, Instagram
y archivos locales. Usa Groq Whisper (whisper-large-v3) y la API de YouTube
Transcript cuando aplica.


Configuracion basica

Necesitas una GROQ_API_KEY. Ponela como variable de entorno o en .streamlit/secrets.toml:

    GROQ_API_KEY = "tu_api_key"

ffmpeg debe estar en el PATH (para extraer audio de archivos locales).
En Windows: scoop install ffmpeg  (o choco install ffmpeg).
En deploy (Streamlit Cloud) ya viene declarado en packages.txt.


Como funciona Instagram

Instagram cerro su API a usuarios sin sesion, asi que el metodo viejo fallaba con
"empty media response". Pero el reproductor sigue cargando el video por detras del
modal de login: la pagina /reel/{code}/embed/captioned/ expone la URL firmada del
mp4 en su HTML, accesible sin login.

La app aprovecha eso: baja ese embed con impersonation de Chrome, extrae el mp4 y
saca el audio con ffmpeg. No necesita cookies ni cuenta. Funciona para reels y
posts publicos, tanto en local como en deploy.

Si Instagram llegara a cambiar la estructura del embed, la app cae automaticamente
a yt-dlp como respaldo.


Otras plataformas

YouTube, TikTok y Twitter/X funcionan directo. TikTok usa impersonation TLS
(curl_cffi, ya incluido en requirements).
