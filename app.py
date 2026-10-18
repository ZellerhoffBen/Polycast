from services.scrape_article import scrape_article
from openai import OpenAI
import os
from dotenv import load_dotenv
from services.pcm2wav import convert2wav
import streamlit as st
from services.process_article import process_article
from pathlib import Path

load_dotenv()

API_KEY = os.getenv("API_KEY")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=API_KEY,
)

st.title("Vinte")
st.write("Learn languages by listening to the news.")

article_url = st.text_input("What article would you like to listen to?")

language = st.selectbox("Language", ["English", "French", "Portuguese", "German"])

language_level = st.selectbox("Level", ["A1", "A2", "B1", "B2", "C1", "C2"])

if st.button("Generate Audio"):
    with st.spinner("Audio wird generiert...", show_time=True):
        audio_file = process_article(article_url, client, language, language_level)
        if audio_file:
            st.audio(audio_file)
