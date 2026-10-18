from services.scrape_article import scrape_article
from prompts.instructions import get_system_prompt
from services.pcm2wav import convert2wav
import tempfile


# simplify the article
def simplify_text(article_text, client, language, language_level):
    system_prompt = get_system_prompt(language, language_level)
    response = client.responses.create(
        model="google/gemini-2.5-flash-lite",
        input=article_text,
        instructions=system_prompt,
    )
    return response.output_text


# text to speech
def text2speech(simplified_article, client, temp_path):
    with client.audio.speech.with_streaming_response.create(
        model="google/gemini-3.1-flash-tts-preview",
        input=simplified_article,
        voice="Orus",
        response_format="pcm",
    ) as response:
        response.stream_to_file(f"{temp_path}/output.pcm")


def process_article(article_url, client, language, language_level):

    temp_dir = tempfile.TemporaryDirectory()
    temp_path = temp_dir.name

    # Get article text
    article_text = scrape_article(article_url)

    simplified_article = simplify_text(article_text, client, language, language_level)

    text2speech(simplified_article, client, temp_path)

    convert2wav(f"{temp_path}/output.pcm", f"{temp_path}/output.wav")

    with open(f"{temp_path}/output.wav", "rb") as wav:
        wav_bytes = wav.read()
        temp_dir.cleanup()
        return wav_bytes
