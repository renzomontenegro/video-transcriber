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
    else:
        st.error(f"❌ {result['error']}")
