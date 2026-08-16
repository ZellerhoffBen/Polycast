from scrape_article import scrape_article
from openai import OpenAI
import os
from dotenv import load_dotenv
from prompts.instructions import system_prompt
from pcm2wav import convert2wav

load_dotenv()

API_KEY = os.getenv("API_KEY")

client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=API_KEY,
    )

def simplify_text(article_text):
    response = client.responses.create(
        model="google/gemini-2.5-flash-lite",
        input=article_text,
        instructions=system_prompt,
    )
    return response.output_text

# Get article text
article_text = scrape_article("https://www.srf.ch/news/schweiz/zwischen-party-und-risiko-die-street-parade-und-der-wandel-des-drogenmarkts")

#simplify the article
simplified_article = simplify_text(article_text)

# text to speech
with client.audio.speech.with_streaming_response.create(
  model="google/gemini-3.1-flash-tts-preview",
  input=simplified_article,
  voice="Orus",
  response_format="pcm"
) as response:
  response.stream_to_file("output.pcm")

convert2wav("output.pcm" ,"output.wav")




