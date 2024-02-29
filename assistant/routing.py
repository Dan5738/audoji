from django.urls import path

from assistant.audojiconsumers import AudioSegmentConsumer
from assistant.consumers import ChatConsumer

websocket_urlpatterns = [
    path("ws/chat/", ChatConsumer.as_asgi()),
    path("ws/audiosegments/", AudioSegmentConsumer.as_asgi()),
]
# wss://bookish-carnival-9pv76g5w4vc956g-8000.app.github.dev/ws/audiosegments/?owner_id=63a6af57677ed8a015025a62
