Video Transcriber

App Streamlit para transcribir videos de YouTube, TikTok, Twitter/X, Instagram
y archivos locales. Usa Groq Whisper (whisper-large-v3) y la API de YouTube
Transcript cuando aplica.


Configuracion basica

Necesitas una GROQ_API_KEY. Ponela como variable de entorno o en .streamlit/secrets.toml:

    GROQ_API_KEY = "tu_api_key"

ffmpeg debe estar en el PATH (para extraer audio de archivos locales).
En Windows: scoop install ffmpeg  (o choco install ffmpeg).


Instagram (como funciona)

Instagram bloquea su API para usuarios sin sesion iniciada, asi que yt-dlp devuelve
"empty media response". Pero el reproductor de Instagram sigue cargando el video por
detras del modal de login: la pagina de "embed captioned" expone la URL firmada del
mp4 en su HTML, accesible SIN cookies.

La app aprovecha eso: para Instagram intenta primero ese metodo directo (bajar el
embed con impersonation de Chrome, extraer el mp4 y sacar el audio con ffmpeg). No
necesita cookies ni login. Funciona para reels y posts publicos.

Las cookies quedan solo como RESPALDO, por si Instagram cambia el embed o el reel es
privado / con restriccion de edad. Si no configuras cookies, igual funciona para el
99% de los casos publicos.

Nota: este metodo depende de la estructura del embed de Instagram. Si en algun momento
deja de funcionar, configura cookies (abajo) y la app caera automaticamente a yt-dlp.


Cookies de Instagram (respaldo opcional)

En Windows reciente, la opcion automatica (--cookies-from-browser) suele fallar:
Chrome bloquea su base de cookies si esta abierto, y Edge/Chrome usan App-Bound
Encryption que yt-dlp ya no puede desencriptar. Por eso lo recomendado es exportar
un archivo cookies.txt una sola vez.

Pasos para exportar cookies.txt:

1. Instala la extension "Get cookies.txt LOCALLY" en Chrome o Edge.
2. Abri instagram.com logueado con tu cuenta.
3. Con la extension, exporta las cookies del sitio a un archivo, por ejemplo:
   C:\Users\lmontenegro_mailamer\Desktop\ig_cookies.txt
4. El archivo debe estar en formato Netscape (es el default de la extension).

Como configurar las cookies (elegi UNA opcion):

Opcion 1 - LOCAL, por ruta de archivo (recomendado en tu PC):
   Seteá la variable de entorno YTDLP_COOKIES_FILE con la ruta del cookies.txt.
   O agregala a .streamlit/secrets.toml:

       YTDLP_COOKIES_FILE = "C:\\Users\\lmontenegro_mailamer\\Desktop\\ig_cookies.txt"

Opcion 2 - DEPLOY (Streamlit Cloud), pegando el contenido:
   Copia el contenido del cookies.txt y pegalo en el secret YTDLP_COOKIES.

Opcion 3 - Navegador automatico (puede fallar en Windows):
   YTDLP_COOKIES_FROM_BROWSER = "chrome"   (o edge / firefox / brave)
   Nota: cerra el navegador antes de transcribir, porque bloquea sus cookies.


Importante sobre las cookies

Las cookies dan acceso a tu sesion de Instagram. No las subas a un repo publico
ni las compartas. Caducan cada cierto tiempo: si Instagram vuelve a fallar,
reexporta el cookies.txt. Usa una cuenta secundaria si te preocupa la seguridad.


Otras plataformas

YouTube, TikTok y Twitter/X funcionan sin cookies. TikTok usa impersonation TLS
(curl_cffi, ya incluido en requirements).
