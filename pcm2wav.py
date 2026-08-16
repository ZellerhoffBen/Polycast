import wave

def convert2wav(pcm_file, wav_file):


    sample_rate = 24000
    channels = 1
    sample_width = 2 

    with open(pcm_file, "rb") as pcm:
        pcm_data = pcm.read()

    with wave.open(wav_file, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_data)

    print("Created", wav_file)