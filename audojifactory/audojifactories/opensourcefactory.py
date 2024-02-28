import io
import json
import os
import tempfile

import librosa
import openai
import requests
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.files.base import ContentFile
from openai import AsyncOpenAI
from pydub import AudioSegment as AudioSegmentCreator

from audojiengine.logging_config import configure_logger
from audojiengine.mg_database import store_data_to_audio_segment_mgdb
from audojifactory.models import AudioSegment as AudioSegmentModel
from audojifactory.serializers import AudioSegmentSerializer

openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
logger = configure_logger(__name__)


class AudioProcessor:
    def __init__(self, audio_file_instance, group_name=None):
        import whisper

        self.group_name = group_name
        self.audio_file_instance = audio_file_instance
        # self.audio_path = audio_file_instance.audio_file.path
        self.audio_path = audio_file_instance.audio_file.url
        self.model = whisper.load_model(
            "base"
        )  # "base", "medium", "large-v1", "large-v2", "large-v3", "large"

    async def send_segment_to_group(self, segment_data):
        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            self.group_name,
            {
                "type": "audio.segment",
                "message": segment_data,
            },
        )

    async def transcribe_audio(self):
        return self.model.transcribe(self.audio_path)

    async def analyze_category_async(self, transcription):
        logger.info("Analysing categories")

        categories = "Affection, Gratitude, Apologies, Excitement, Disinterest, Well-being, Greetings"

        prompt = f"""Here's an example of how I want you to categorize the text: \n
            Text: 'I feel amazing today!' Response: {{'category': 'Excitement'}}\n\n
            Now, using the same format, categorize the following text as {categories}, and respond in JSON format: \n
            Text: '{transcription}'\nResponse: 

            # SAMPLE FORMAT:
            {{'category': 'Excitement'}}"""

        try:
            response = await openai_client.chat.completions.create(
                model="gpt-4-1106-preview",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                response_format={"type": "json_object"},
            )
            processed_response = json.loads(response.choices[0].message.content)
            logger.info(f"This is the response: {processed_response}")
            category = processed_response.get("category", None)
            return category
        except openai.APIError as e:
            logger.error(f"OpenAI API error: {e}")
            return None

    async def process_and_save_segments(self, result):
        logger.info("Processing Started")
        segments_data = []

        for i, segment in enumerate(result["segments"]):
            transcription = segment.get("text", "").strip()
            category = await self.analyze_category_async(transcription)

            start = segment["start"]
            end = segment["end"]

            # Create a segment instance and save it to the database
            segment_data = {
                "audio_file": self.audio_file_instance,
                "start_time": start,
                "end_time": end,
                "transcription": transcription,
                "category": category,
            }
            audio_segment_instance = AudioSegmentModel(**segment_data)

            await sync_to_async(audio_segment_instance.save)()

            # ==================== Create Audoji ====================
            create_audoji_sync = sync_to_async(
                AudioRetrieval(audio_segment_instance, start, end).create_audoji
            )
            created_audoji = await create_audoji_sync()

            logger.info(f"Audoji created! {created_audoji}")
            # ==================== Create Audoji ====================

            segment_data["audio_file_id"] = self.audio_file_instance.id

            await self.send_segment_to_group(
                AudioSegmentSerializer(audio_segment_instance).data
            )

            logger.info(
                f"Segment {i} exported and saved: Text: {segment.get('text', '')} | Start - {segment['start']}s, End - {segment['end']}s"
            )

        logger.info("Done Creating Audojis")

    async def run_and_save_segments(self):
        logger.info("Run operation started!")
        transcription_result = await self.transcribe_audio()
        return await self.process_and_save_segments(transcription_result)


class AudioRetrieval:
    def __init__(self, matching_segment_instance, start_time, end_time):
        self.audio_file_instance = matching_segment_instance
        self.segment_id = matching_segment_instance.id
        self.associated_audio_file = (
            # matching_segment_instance.audio_file.audio_file.path
            matching_segment_instance.audio_file.audio_file.url
        )
        self.start_time = start_time
        self.end_time = end_time

    def create_audoji(self):
        # Download the audio file from URL to a bytes buffer
        audio_response = requests.get(self.associated_audio_file)
        audio_bytes = io.BytesIO(audio_response.content)

        # Use Pydub to process the audio from the bytes buffer
        audio = AudioSegmentCreator.from_file(audio_bytes)
        start_ms, end_ms = float(self.start_time * 1000), float(self.end_time * 1000)
        segment_audio = audio[start_ms:end_ms]

        # Create an in-memory file for the segment
        segment_file = io.BytesIO()
        segment_audio.export(segment_file, format="mp3", bitrate="192k")
        segment_file.seek(0)

        # Extract the title of the audio file to use in the segment file name
        audio_title = self.audio_file_instance.audio_file.title
        safe_title = "".join(
            [c if c.isalnum() else "_" for c in audio_title]
        )  # Create a filesystem-safe version of the title
        segment_file_name = f"segment_{self.segment_id}.mp3"

        # Use the custom upload path function if needed
        # segment_file_path = get_segment_upload_path(self.audio_file_instance, segment_file_name)

        self.audio_file_instance.segment_file.save(
            segment_file_name, ContentFile(segment_file.read()), save=False
        )
        self.audio_file_instance.save()

        segment_info = {
            "id": self.audio_file_instance.id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "transcription": self.audio_file_instance.transcription,
            "file_url": self.audio_file_instance.segment_file.url,
        }
        return segment_info


# # Usage
# # audio_path = r"C:\Users\pc\Desktop\audoji\Sam-Smith-Beautiful.mp3"
# audio_path = r"C:\Users\pc\Desktop\audoji\Sam-Smith-Man-I-Am.mp3"
# processor = AudioProcessor(audio_path)
# processor.run()
