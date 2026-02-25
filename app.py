import streamlit as st
from transcriber import transcribe_url

st.set_page_config(page_title="Video Transcriber", page_icon="🎙️", layout="centered")

st.title("🎙️ Video Transcriber")
st.caption("YouTube · TikTok · Twitter/X · Instagram · cualquier video")

url = st.text_input("Pega el link del video", placeholder="https://...")

if st.button("Transcribir", type="primary", disabled=not url):
    with st.spinner("Procesando..."):
        result = transcribe_url(url)

    if result["success"]:
        st.success(f"✅ Listo · plataforma: `{result['platform']}` · método: `{result['method']}`")
        st.text_area("Transcripción", value=result["text"], height=400)
        st.download_button(
            "⬇️ Descargar .txt",
            data=result["text"],
            file_name="transcripcion.txt",
            mime="text/plain"
        )

        # Botón para copiar al portapapeles
        transcription_text = result["text"]
        escaped_text = transcription_text.replace("`", "\\`").replace("${", "\\${")
        html_code = f"""
            <script>
            function copyToClipboard() {{
                const text = `{escaped_text}`;
                navigator.clipboard.writeText(text).then(() => {{
                    document.getElementById('copyFeedback').style.display = 'block';
                    setTimeout(() => {{
                        document.getElementById('copyFeedback').style.display = 'none';
                    }}, 2000);
                }}).catch(err => {{
                    console.error("Error:", err);
                }});
            }}
            </script>
            <style>
            .copy-btn {{
                background-color: #FF4B4B;
                color: white;
                border: none;
                padding: 0.5rem 1rem;
                border-radius: 0.3rem;
                cursor: pointer;
                font-size: 0.9rem;
            }}
            .copy-btn:hover {{
                background-color: #ff6b6b;
            }}
            #copyFeedback {{
                display: none;
                color: green;
                margin-left: 10px;
                font-size: 0.9rem;
            }}
            </style>
            <button class="copy-btn" onclick="copyToClipboard()">📋 Copiar</button>
            <span id="copyFeedback">✅ Copiado</span>
        """
        st.components.v1.html(html_code, height=50)
    else:
        st.error(f"❌ {result['error']}")
