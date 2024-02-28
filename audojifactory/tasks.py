import asyncio

from celery import shared_task

from audojiengine.mg_database import store_data_to_audio_mgdb
from audojifactory.audojifactories.apifactory import AudioProcessor as APIAudioProcessor
from audojifactory.audojifactories.opensourcefactory import (
    AudioProcessor as OSAudioProcessor,
)
from audojifactory.models import AudioFile


@shared_task
def task_run_async_processor(audio_file_instance_id, model_type, group_name=None):
    # Retrieve the audio file instance by ID
    audio_file_instance = AudioFile.objects.get(id=audio_file_instance_id)

    # Setup event loop for async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    if model_type == "os":
        audio_processor = OSAudioProcessor(audio_file_instance, group_name)
    else:
        audio_processor = APIAudioProcessor(audio_file_instance)

    # Run the processor asynchronously
    loop.run_until_complete(audio_processor.run_and_save_segments())
    loop.close()


@shared_task
def task_run_async_db_operation(data):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(store_data_to_audio_mgdb(data))
    loop.close()
