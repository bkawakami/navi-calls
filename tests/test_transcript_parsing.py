from app.services.transcript_service import TranscriptService

REALTIME_PAYLOAD = {
    "event": "transcript.data",
    "data": {
        "data": {
            "words": [
                {"text": "Precisamos", "start_timestamp": {"relative": 12.1}, "end_timestamp": {"relative": 12.6}},
                {"text": "decidir", "start_timestamp": {"relative": 12.7}, "end_timestamp": {"relative": 13.0}},
                {"text": "até sexta.", "start_timestamp": {"relative": 13.1}, "end_timestamp": None},
            ],
            "language_code": "pt",
            "participant": {"id": 100, "name": "Ana Souza", "is_host": True, "platform": "microsoft_teams", "extra_data": None, "email": None},
        },
        "realtime_endpoint": {"id": "rt_1", "metadata": {}},
        "transcript": {"id": "tr_1", "metadata": {}},
        "recording": {"id": "rec_1", "metadata": {}},
        "bot": {"id": "bot_1", "metadata": {"meeting_id": "m1"}},
    },
}


def test_parse_realtime_event():
    parsed = TranscriptService.parse_realtime_event(REALTIME_PAYLOAD)
    assert parsed["event"] == "transcript.data"
    assert parsed["bot_id"] == "bot_1"
    assert parsed["speaker"] == "Ana Souza"
    assert parsed["text"] == "Precisamos decidir até sexta."
    assert parsed["start_ts"] == 12.1
    assert parsed["end_ts"] == 13.0  # último end_timestamp não nulo
    assert parsed["language"] == "pt"


def test_parse_final_transcript_utterance_with_absolute():
    utt = {
        "participant": {"id": 2147483647, "name": None, "is_host": None, "platform": None, "extra_data": None, "email": None},
        "language_code": "pt-BR",
        "words": [{"text": "Anotado.", "start_timestamp": {"absolute": "2026-11-05T15:00:01.000Z", "relative": 30.0}, "end_timestamp": {"absolute": "2026-11-05T15:00:02.000Z", "relative": 31.0}}],
    }
    parsed = TranscriptService.parse_utterance(utt)
    assert parsed["speaker"] == "Navi"
    assert parsed["absolute"] == "2026-11-05T15:00:01.000Z"


def test_parse_empty_words_returns_none():
    assert TranscriptService.parse_utterance({"words": [], "participant": {"name": "x"}}) is None
