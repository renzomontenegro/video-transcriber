import streamlit as st
from transcriber import transcribe_url, transcribe_file, transcribe_local_path

st.set_page_config(page_title="Video Transcriber", page_icon="🎙️", layout="centered")

st.title("🎙️ Video Transcriber")
st.caption("YouTube · TikTok · Twitter/X · Instagram · archivos de video")


def _copy_button(text: str):
    """Render a stylish clipboard copy button via HTML component."""
    escaped = text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    html = f"""
    <style>
      .copy-wrap {{ display: flex; align-items: center; gap: 10px; margin-top: 4px; }}
      .copy-btn {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: #fff;
        border: none;
        padding: 0.55rem 1.3rem;
        border-radius: 8px;
        cursor: pointer;
        font-size: 0.88rem;
        font-weight: 600;
        letter-spacing: 0.04em;
        box-shadow: 0 3px 10px rgba(102,126,234,0.45);
        transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.3s ease;
        outline: none;
      }}
      .copy-btn:hover {{
        transform: translateY(-2px);
        box-shadow: 0 6px 18px rgba(102,126,234,0.55);
      }}
      .copy-btn:active {{
        transform: translateY(0);
        box-shadow: 0 2px 6px rgba(102,126,234,0.3);
      }}
      .copy-btn.ok {{
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        box-shadow: 0 3px 10px rgba(17,153,142,0.45);
      }}
      .copy-badge {{
        opacity: 0;
        font-size: 0.82rem;
        color: #38ef7d;
        font-weight: 600;
        transition: opacity 0.2s ease;
      }}
      .copy-badge.show {{ opacity: 1; }}
    </style>
    <div class="copy-wrap">
      <button class="copy-btn" id="cpBtn" onclick="doCopy()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2"/>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
        </svg>
        Copiar al portapapeles
      </button>
      <span class="copy-badge" id="cpBadge">✓ Copiado</span>
    </div>
    <script>
      function doCopy() {{
        const t = `{escaped}`;
        const btn = document.getElementById('cpBtn');
        const badge = document.getElementById('cpBadge');
        navigator.clipboard.writeText(t).then(() => {{
          btn.classList.add('ok');
          btn.childNodes[2].nodeValue = ' Copiado';
          badge.classList.add('show');
          setTimeout(() => {{
            btn.classList.remove('ok');
            btn.childNodes[2].nodeValue = ' Copiar al portapapeles';
            badge.classList.remove('show');
          }}, 2500);
        }}).catch(() => {{
          btn.childNodes[2].nodeValue = ' Error';
          setTimeout(() => {{ btn.childNodes[2].nodeValue = ' Copiar al portapapeles'; }}, 2000);
        }});
      }}
    </script>
    """
    st.components.v1.html(html, height=56)


def show_result(result: dict):
    if result["success"]:
        st.success(
            f"✅ Listo · plataforma: `{result['platform']}` · método: `{result['method']}`"
        )
        st.text_area("Transcripción", value=result["text"], height=400)
        col1, col2 = st.columns([1, 3])
        with col1:
            st.download_button(
                "⬇️ Descargar .txt",
                data=result["text"],
                file_name="transcripcion.txt",
                mime="text/plain",
            )
        _copy_button(result["text"])
    else:
        st.error(f"❌ {result['error']}")


tab_url, tab_file, tab_path = st.tabs(["🔗 URL", "📁 Subir archivo", "📂 Ruta local"])

with tab_url:
    url = st.text_input("Pega el link del video", placeholder="https://...")
    if st.button("Transcribir", type="primary", disabled=not url, key="btn_url"):
        with st.spinner("Procesando..."):
            result = transcribe_url(url)
        show_result(result)

with tab_file:
    st.info(
        "Soporta MP4, MOV, AVI, MKV, WEBM y más. "
        "Límite: **500 MB**. Para videos más pesados usa la pestaña **Ruta local**."
    )
    uploaded = st.file_uploader(
        "Sube tu video",
        type=["mp4", "mov", "avi", "mkv", "webm", "m4v", "flv", "wmv"],
        help="El audio se extrae con ffmpeg y se transcribe con Groq Whisper.",
    )
    if uploaded:
        st.caption(f"Archivo: **{uploaded.name}** · {uploaded.size / 1_048_576:.1f} MB")
        if st.button("Transcribir archivo", type="primary", key="btn_file"):
            with st.spinner(f"Extrayendo y transcribiendo `{uploaded.name}`…"):
                result = transcribe_file(uploaded, uploaded.name)
            show_result(result)

with tab_path:
    st.info(
        "Para videos **grandes (2 GB+)**: indica la ruta en disco. "
        "ffmpeg lee el archivo directo, sin cargarlo en memoria."
    )
    path_input = st.text_input(
        "Ruta del archivo de video",
        placeholder="C:/Videos/clase.mp4  ·  /home/user/pelicula.mkv",
    )
    if path_input:
        p = __import__("pathlib").Path(path_input)
        if p.exists():
            size_gb = p.stat().st_size / 1_073_741_824
            st.caption(f"✔ Encontrado · {size_gb:.2f} GB")
        else:
            st.warning("Archivo no encontrado. Verifica la ruta.")
    if st.button("Transcribir ruta local", type="primary",
                 disabled=not path_input, key="btn_path"):
        with st.spinner("Procesando…"):
            result = transcribe_local_path(path_input)
        show_result(result)
