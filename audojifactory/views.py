import asyncio
import time
from threading import Thread

from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from audojiengine.logging_config import configure_logger
from audojiengine.mg_database import store_data_to_audio_mgdb
from audojifactory.audojifactories.opensourcefactory import (
    AudioRetrieval as OSAudioRetrieval,
)
from audojifactory.models import AudioFile, AudioSegment
from audojifactory.serializers import AudioFileSerializer, AudioSegmentSerializer
from audojifactory.tasks import task_run_async_db_operation, task_run_async_processor

logger = configure_logger(__name__)


def run_async_processor(processor):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(processor.run_and_save_segments())
    loop.close()


def run_async_db_operation(data):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(store_data_to_audio_mgdb(data))
    loop.close()


class AudioFileList(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def get(self, request):
        audio_files = AudioFile.objects.all()
        serializer = AudioFileSerializer(audio_files, many=True)
        return Response(serializer.data)

    def post(self, request):
        process_start_time = time.time()
        responses = []

        # Count the number of files uploaded
        num_files = sum("file[" in key for key in request.FILES.keys())

        for i in range(num_files):
            audio_file_data = request.FILES.get(f"audio_file[{i}]")
            artiste = request.data.get(f"artiste[{i}]")
            title = request.data.get(f"title[{i}]")
            owner_id = request.data.get(f"owner[{i}]")
            cover_image = request.data.get(f"cover_image[{i}]")
            terms_condition = request.data.get(f"terms_condition[{i}]")

            if audio_file_data:
                data = {
                    "owner": owner_id,
                    "audio_file": audio_file_data,
                    "artiste": artiste,
                    "title": title,
                    "cover_image": cover_image,
                    "terms_condition": terms_condition,
                }

                serializer = AudioFileSerializer(data=data)
                if serializer.is_valid():
                    audio_file_instance = serializer.save()
                    data["audio_file"] = audio_file_instance.audio_file.url
                    db_thread = Thread(target=run_async_db_operation, args=(data,))
                    db_thread.start()

                    # Set a default of os
                    model_type = request.query_params.get("model_type", "os")

                    # # Call the Celery task for DB operation
                    # task_run_async_db_operation.delay(data)

                    # Call the Celery task for processing
                    task_run_async_processor.delay(audio_file_instance.id, model_type)

                    duration = time.time() - process_start_time
                    logger.info(f"CREATION DURATION: {duration:.2f} seconds")

                    responses.append({"audio": audio_file_instance.audio_file.url})
                else:
                    # Collect errors if the serializer is not valid
                    responses.append(
                        {
                            "audio_file": audio_file_data.name,
                            "errors": serializer.errors,
                        }
                    )
            else:
                # Handle the case where no file is found
                responses.append({"error": f"No Song file found for index {i}"})

        # Return the collected responses for all files processed
        return Response(responses, status=status.HTTP_201_CREATED)


class AudioSegmentList(APIView):
    """
    GET: Retrieve a list of all audio segments.

    This endpoint provides a list of all audio segments available in the system. Each audio segment contains details such as start time, end time, associated audio file, transcription, and mood.

    Response Format:
    [
        {
            "id": int,
            "audio_file": int,          // ID of the associated audio file
            "start_time": float,
            "end_time": float,
            "segment_file": str,        // URL to the segment file
            "transcription": str,
            "mood": str
        },
        ...
    ]

    This endpoint does not require any query parameters and returns a list of all segments in JSON format.
    """

    def get(self, request):
        audio_segments = AudioSegment.objects.all()
        serializer = AudioSegmentSerializer(audio_segments, many=True)
        return Response(serializer.data)


class SearchAudoji(APIView):
    """
    POST: Search for audio segments based on various criteria.

    Input:
    - query: The main search term (mandatory).
    - additionalFilter: Optional filters including artiste name and song title.

    Request JSON Structure:
    {
        "query": "search term",
        "additionalFilter": {
            "artiste": "Artist Name",
            "title": "Song Title"
        }
    }

    Output:
    - A list of audio segments matching the search criteria.
    - Each segment contains transcription, start and end times, and mood.

    Returns:
    [
        {
            "transcription": "text",
            "start_time": float,
            "end_time": float,
            "mood": "mood"
        },
        ...
    ]
    """

    def get(self, request):
        process_start_time = time.time()
        query_data = request.data

        query = query_data.get("query")
        artiste = query_data.get("additionalFilter", {}).get("artiste")
        title = query_data.get("additionalFilter", {}).get("title")

        if not query:
            return Response(
                {"error": "No search query provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        matching_segment_instance = AudioSegment.objects.filter(
            transcription__icontains=query
        ).first()

        if not matching_segment_instance:
            return Response(
                {"message": "Audoji segment not found!"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # audio_segment_creator = OSAudioRetrieval(matching_segment_instance)
        # segment_info = audio_segment_creator.create_audoji()
        # duration = time.time() - process_start_time
        # logger.info(f"CREATION DURATION: {duration:.2f} seconds")
        segment_info = {"segment_info": "segment_info"}
        return Response(segment_info)


class GetAudoji(APIView):
    """
    POST: Retrieve a specific audio segment based on transcription and time range.

    Input:
    - query: Transcription text to match (mandatory).
    - start_time: Starting time of the segment (mandatory).
    - end_time: Ending time of the segment (mandatory).

    Request JSON Structure:
    {
        "query": "transcription text",
        "start_time": float,
        "end_time": float
    }

    Output:
    - Details of the matching audio segment.
    - Includes ID, transcription, start and end times, and file URL.

    Returns:
    {
        "id": int,
        "start_time": float,
        "end_time": float,
        "transcription": "text",
        "file_url": "url"
    }
    """

    def post(self, request):
        process_start_time = time.time()
        query_data = request.data

        query = query_data.get("query")
        start_time = query_data.get("start_time")
        end_time = query_data.get("end_time")

        segment_instance = AudioSegment.objects.get(
            transcription=query, start_time=start_time, end_time=end_time
        )
        segment_info = OSAudioRetrieval(
            segment_instance, start_time, end_time
        ).create_audoji()

        duration = time.time() - process_start_time
        logger.info(f"AUDOJI CREATION DURATION: {duration:.2f} seconds")
        return Response(segment_info)


# {
#     'user[0]': ['1'],
#     'title[0]': ['Beautiful'],
#     'artiste[0]': ['Sam Smith'],
#     'user[1]': ['2'],
#     'title[1]': ['Man I Am'],
#     'artiste[1]': ['Sam Smith'],
#     'file[0]': [<TemporaryUploadedFile: Sam-Smith-Beautiful.mp3 (audio/mpeg)>],
#     'file[1]': [<TemporaryUploadedFile: Sam-Smith-Man-I-Am.mp3 (audio/mpeg)>]
# }
