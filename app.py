import logging
from fastapi import FastAPI, HTTPException, Request, Header, Depends
from pydantic import BaseModel
from openai import AsyncOpenAI
import os
import requests
import json
import io
from fastapi import UploadFile, File
from fastapi.responses import StreamingResponse, HTMLResponse

## TODO  FOR LOCAL DEBUGGING
# from dotenv import load_dotenv
# load_dotenv()
## TODO FOR LOCAL DEBUGGING

# Load environment variables
api_key = os.getenv("OPENAI_API_KEY")
elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")
stt_api_key = os.getenv("STT_API_KEY")
elevenlabs_voice_id = os.getenv("ELEVENLABS_VOICE_ID")

# Initialize FastAPI app
app = FastAPI()

# Initialize the OpenAI async client
client = AsyncOpenAI(api_key=api_key)

class TextRequest(BaseModel):
    prompt: str

def require_api_key(x_api_key: str = Header(...)):
    expected_api_key = os.getenv("PROXY_API_KEY")  # Set this in your .env file
    if x_api_key != expected_api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")

@app.post("/generate-text/", dependencies=[Depends(require_api_key)])
async def generate_text(text_request: TextRequest):
    try:
        # Create the messages array as expected by the API
        messages = [
            {"role": "system", "content": "Aurora is concice, curious and goodhearted. She is booksmart and clever, which sometimes leads to a confidence that teeters towards bossiness and a frazzled reaction when she doesn’t know what to do. But despite everything, she is dutiful and kind, especially to the helpless. The player can always rely on her to lead the way to adventures that foster one’s curiosity and offer magnanimous solutions to any dilemma."},
            {"role": "user", "content": text_request.prompt},
        ]

        # Call the OpenAI API asynchronously to generate a response
        response = await client.chat.completions.create(
            model="gpt-4o",  # Ensure to use the correct model ID for GPT-4o
            messages=messages,
            max_tokens=1024,
        )
        # Return the generated text
        return {"response": response.choices[0].message.content}  # Adjusted the attribute access here
    except Exception as e:
        # Log the error
        logging.error(f"Error occurred: {str(e)}")
        # Raise an HTTP 500 error
        raise HTTPException(status_code=500, detail="An error occurred on the server.")

@app.post("/text-to-speech/", dependencies=[Depends(require_api_key)])
async def text_to_speech(text_request: TextRequest):
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{elevenlabs_voice_id}"
        headers = {
            "xi-api-key": elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        }
        payload = {
            "text": text_request.prompt,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.5
            }
        }

        response = requests.post(url, headers=headers, data=json.dumps(payload))

        if response.status_code == 200:
            # Stream audio from Eleven Labs to the client
            audio_stream = io.BytesIO(response.content)
            return StreamingResponse(audio_stream, media_type="audio/mpeg")
        else:
            logging.error(f"Error {response.status_code}: {response.text}")
            raise HTTPException(status_code=response.status_code, detail="Error occurred with TTS request.")
    except Exception as e:
        logging.error(f"Error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail="An error occurred on the server.")

@app.post("/speech-to-text/", dependencies=[Depends(require_api_key)])
async def speech_to_text(file: bytes = File(...)):
    try:
        url = "https://eastus.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2024-05-15-preview"
        headers = {
            "Ocp-Apim-Subscription-Key": stt_api_key,
            "Accept": "application/json"
        }
        
        files = {
            'audio': ('audio.wav', file, 'audio/wav'),
            'definition': (None, '{"locales":["en-US"], "profanityFilterMode": "Masked", "channels": [0,1]}', 'application/json')
        }

        response = requests.post(url, headers=headers, files=files)

        if response.status_code == 200:
            result = response.json()
            channel_number = 0
            combined_phrases = result.get('combinedPhrases', [])
            text = next((phrase['text'] for phrase in combined_phrases if phrase['channel'] == channel_number), None)
            return {"transcription": text if text else f"No transcription text found for channel {channel_number}"}
        else:
            logging.error(f"STT Error {response.status_code}: {response.text}")
            raise HTTPException(status_code=response.status_code, detail="Error with STT request.")
    except Exception as e:
        logging.error(f"Error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail="An error occurred on the server.")


# Voice-to-Voice: Combine speech-to-text, text generation, and text-to-speech
@app.post("/voice-to-voice/", dependencies=[Depends(require_api_key)])
async def voice_to_voice(request: Request):
    try:
        # Step 1: Speech-to-Text
        form = await request.form()
        audio_file = form.get("file")
        
        if not audio_file:
            raise HTTPException(status_code=400, detail="No file provided")
        
        file_bytes = await audio_file.read()
        logging.info("File received for speech-to-text processing")

        # Pass the file bytes directly to speech_to_text
        stt_result = await speech_to_text(file_bytes)
        transcribed_text = stt_result.get('transcription')

        if not transcribed_text:
            raise HTTPException(status_code=400, detail="No transcription available from the speech input")
        
        logging.info(f"Transcribed text: {transcribed_text}")
        
        # Step 2: Text Generation using OpenAI
        generated_text = await generate_text(TextRequest(prompt=transcribed_text))
        logging.info(f"Generated text: {generated_text['response']}")
        
        # Step 3: Text-to-Speech with Eleven Labs
        tts_response = await text_to_speech(TextRequest(prompt=generated_text['response']))
        logging.info("Text-to-speech conversion completed")

        return tts_response
    except Exception as e:
        logging.error(f"Voice-to-Voice Error: {str(e)}")
        raise HTTPException(status_code=500, detail="An error occurred during the voice-to-voice process.")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    content = """
    <html>
        <head>
            <title>All-In-One AI Service</title>
        </head>
        <body>
            <h1>All-In-One AI Service</h1>

            <p>Welcome to the All-In-One AI Service! This API offers several endpoints for Text Generation, Text-to-Speech, Speech-to-Text, and combines them into a Voice-to-Voice feature for seamless interaction.</p>

            <h2>Available Endpoints</h2>
            <ul>
                <li><code>/generate-text/</code>: Send a prompt to the LLM and receive a response.</li>
                <li><code>/text-to-speech/</code>: Convert text to speech using Eleven Labs API.</li>
                <li><code>/speech-to-text/</code>: Convert speech to text using Microsoft's Speech-to-Text API.</li>
                <li><code>/voice-to-voice/</code>: Transcribe speech to text, generate a response using LLM, and convert that response back to speech.</li>
            </ul>

            <h2>Endpoint Details</h2>

            <h3>1. Generate Text</h3>
            <p>Send a prompt to the LLM and receive a response.</p>
            <ul>
                <li><strong>Method</strong>: POST</li>
                <li><strong>Endpoint</strong>: <code>/generate-text/</code></li>
                <li><strong>Headers</strong>:
                    <ul>
                        <li><code>Content-Type: application/json</code></li>
                        <li><code>x-api-key: your-api-key-here</code></li>
                    </ul>
                </li>
                <li><strong>Body</strong>: JSON object in the following format:
                    <pre><code>{
    "prompt": "Your text prompt here"
}</code></pre>
                </li>
                <li><strong>Response</strong>: JSON object containing the generated text:
                    <pre><code>{
    "response": "Generated response from the LLM"
}</code></pre>
                </li>
            </ul>

            <h3>2. Text to Speech</h3>
            <p>Convert text to speech using Eleven Labs API.</p>
            <ul>
                <li><strong>Method</strong>: POST</li>
                <li><strong>Endpoint</strong>: <code>/text-to-speech/</code></li>
                <li><strong>Headers</strong>:
                    <ul>
                        <li><code>Content-Type: application/json</code></li>
                        <li><code>x-api-key: your-api-key-here</code></li>
                    </ul>
                </li>
                <li><strong>Body</strong>: JSON object in the following format:
                    <pre><code>{
    "prompt": "Your text to convert to speech"
}</code></pre>
                </li>
                <li><strong>Response</strong>: Streaming audio (MPEG format).</li>
            </ul>

            <h3>3. Speech to Text</h3>
            <p>Convert speech to text using Microsoft's Speech-to-Text API.</p>
            <ul>
                <li><strong>Method</strong>: POST</li>
                <li><strong>Endpoint</strong>: <code>/speech-to-text/</code></li>
                <li><strong>Headers</strong>:
                    <ul>
                        <li><code>x-api-key: your-api-key-here</code></li>
                    </ul>
                </li>
                <li><strong>Body</strong>: Form-data with the file field containing the audio file:
                    <pre><code>--form "file=@path_to_audio_file.wav"</code></pre>
                </li>
                <li><strong>Response</strong>: JSON object containing the transcription:
                    <pre><code>{
    "transcription": "Transcribed text from speech"
}</code></pre>
                </li>
            </ul>

            <h3>4. Voice to Voice</h3>
            <p>This endpoint combines Speech-to-Text, Text Generation, and Text-to-Speech into a seamless process. The flow is:
            <ol>
                <li>Speech-to-Text: Transcribes the provided audio into text.</li>
                <li>Text Generation: Uses the transcribed text to generate a response from the LLM.</li>
                <li>Text-to-Speech: Converts the generated text back to speech.</li>
            </ol>
            </p>
            <ul>
                <li><strong>Method</strong>: POST</li>
                <li><strong>Endpoint</strong>: <code>/voice-to-voice/</code></li>
                <li><strong>Headers</strong>:
                    <ul>
                        <li><code>x-api-key: your-api-key-here</code></li>
                    </ul>
                </li>
                <li><strong>Body</strong>: Form-data with the file field containing the audio file:
                    <pre><code>--form "file=@path_to_audio_file.wav"</code></pre>
                </li>
                <li><strong>Response</strong>: Streaming audio (MPEG format) of the generated voice response.</li>
            </ul>

            <h2>More Information</h2>
            <p>For more information about the Voice to Voice system, visit the <a href="https://github.com/TroyDoesAI/Voice-To-Voice">Voice to Voice GitHub repository</a>.</p>

            <h2>How to Use</h2>
            <h3>Example Curl Command for Generate Text</h3>
            <pre><code>curl -X POST /generate-text/ \\
    -H "Content-Type: application/json" \\
    -H "x-api-key: your-api-key-here" \\
    -d "{\\"prompt\\": \\"Your text prompt\\"}"</code></pre>

            <h3>Example Curl Command for Text-to-Speech</h3>
            <pre><code>curl -X POST /text-to-speech/ \\
    -H "Content-Type: application/json" \\
    -H "x-api-key: your-api-key-here" \\
    -d "{\\"prompt\\": \\"Your text\\"}"</code></pre>

            <h3>Example Curl Command for Speech-to-Text</h3>
            <pre><code>curl -X POST /speech-to-text/ \\
    -H "x-api-key: your-api-key-here" \\
    -F "file=@path_to_audio_file.wav"</code></pre>

            <h3>Example Curl Command for Voice-to-Voice</h3>
            <pre><code>curl -X POST /voice-to-voice/ \\
    -H "x-api-key: your-api-key-here" \\
    -F "file=@path_to_audio_file.wav"</code></pre>

        </body>
    </html>
    """
    return content

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
