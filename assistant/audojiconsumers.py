import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from audojifactory.models import AudioFile, AudioSegment
from audojifactory.serializers import AudioSegmentSerializerWebSocket


class AudioSegmentConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Retrieve the user_id from the query string
        self.user_id = self.scope["query_string"].decode("utf-8").split("=")[1]
        self.group_name = f"user_{self.user_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        # Remove this channel from the group
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def send_segment_update(self, message):
        # Call this method to send a message to the WebSocket
        await self.send(text_data=json.dumps(message))

    # This is the handler for messages sent over the channel layer
    # It will be called when a message with the type 'audio.segment' is sent to the group
    async def audio_segment(self, event):
        # Send the actual message
        await self.send(text_data=json.dumps(event["message"]))

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        user_id = text_data_json.get("user_id")
        title = text_data_json.get("title")
        transcription = text_data_json.get("transcription")
        category = text_data_json.get("category")

        segments = await self.get_audio_segments(
            user_id, title, transcription, category
        )
        await self.send(text_data=json.dumps({"segments": segments}))

    @database_sync_to_async
    def get_audio_segments(self, user_id, title, transcription, category):
        audio_files_query = AudioFile.objects.all()

        if user_id:
            audio_files_query = audio_files_query.filter(owner=user_id)
        if title:
            audio_files_query = audio_files_query.filter(title__icontains=title)

        segments_query = AudioSegment.objects.filter(audio_file__in=audio_files_query)

        if transcription:
            segments_query = segments_query.filter(
                transcription__icontains=transcription
            )
        if category:
            segments_query = segments_query.filter(category__icontains=category)

        # Modify the serializer instantiation to include the user_id in the context
        serializer = AudioSegmentSerializerWebSocket(
            segments_query, many=True, context={"user_id": user_id}
        )
        return serializer.data
