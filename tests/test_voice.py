import base64
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "services"))

from services.voice.assistant import (
    classify_intent,
    generate_grounded_answer,
    get_verdict_level,
    load_forecast_for_area,
)
from services.voice.providers import (
    IndicConformerVoiceProvider,
    SarvamVoiceProvider,
    STTError,
    TTSError,
    get_voice_provider,
)


class TestVoiceProviders(unittest.TestCase):
    def test_voice_provider_selection(self):
        with patch.dict(os.environ, {"VOICE_PROVIDER": "sarvam"}):
            p = get_voice_provider()
            self.assertIsInstance(p, SarvamVoiceProvider)
            self.assertEqual(p.name, "sarvam")

        with patch.dict(os.environ, {"VOICE_PROVIDER": "indicconformer"}):
            p = get_voice_provider()
            self.assertIsInstance(p, IndicConformerVoiceProvider)
            self.assertEqual(p.name, "indicconformer")

    def test_sarvam_configuration(self):
        p_unconf = SarvamVoiceProvider(api_key="")
        self.assertFalse(p_unconf.is_configured())
        self.assertEqual(p_unconf.health()["status"], "unconfigured")

        p_conf = SarvamVoiceProvider(api_key="test_sarvam_key_123")
        self.assertTrue(p_conf.is_configured())
        self.assertEqual(p_conf.health()["status"], "ok")
        self.assertIn("kn-IN", p_conf.health()["supported_langs"])

    def test_sarvam_stt_requires_key(self):
        p = SarvamVoiceProvider(api_key="")
        with self.assertRaises(STTError) as ctx:
            p.transcribe(b"dummy audio" * 20)
        self.assertIn("SARVAM_API_KEY is not configured", str(ctx.exception))

    def test_sarvam_stt_rejects_empty_audio(self):
        p = SarvamVoiceProvider(api_key="valid_key")
        with self.assertRaises(STTError) as ctx:
            p.transcribe(b"")
        self.assertIn("empty or too short", str(ctx.exception))

    @patch("requests.post")
    def test_sarvam_stt_request_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "transcript": "ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?",
            "language_code": "kn-IN",
        }
        mock_post.return_value = mock_resp

        p = SarvamVoiceProvider(api_key="test_key_abc")
        audio_payload = b"RIFF" + b"\x00" * 200  # mock wav header
        result = p.transcribe(audio_payload, audio_format="wav", lang="kn")

        self.assertEqual(result.transcript, "ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?")
        self.assertEqual(result.language_code, "kn-IN")
        self.assertEqual(result.provider, "sarvam")

        # Verify call arguments
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.sarvam.ai/speech-to-text")
        self.assertEqual(kwargs["headers"]["api-subscription-key"], "test_key_abc")
        self.assertEqual(kwargs["data"]["language_code"], "kn-IN")
        self.assertEqual(kwargs["data"]["model"], "saaras:v4")

    @patch("requests.post")
    def test_sarvam_tts_request_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_audio = b"FAKE_WAV_AUDIO_DATA"
        mock_resp.json.return_value = {
            "audios": [base64.b64encode(mock_audio).decode("ascii")],
        }
        mock_post.return_value = mock_resp

        p = SarvamVoiceProvider(api_key="test_key_abc")
        result = p.synthesize("ನಾಳೆ ಮಳೆ ಬರುವುದು ಖಚಿತವಿಲ್ಲ.", lang="kn")

        self.assertEqual(result.audio_bytes, mock_audio)
        self.assertEqual(result.provider, "sarvam")
        self.assertEqual(result.language_code, "kn-IN")

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.sarvam.ai/text-to-speech")
        self.assertEqual(kwargs["headers"]["api-subscription-key"], "test_key_abc")
        self.assertEqual(kwargs["json"]["text"], "ನಾಳೆ ಮಳೆ ಬರುವುದು ಖಚಿತವಿಲ್ಲ.")
        self.assertEqual(kwargs["json"]["language_code"], "kn-IN")
        self.assertEqual(kwargs["json"]["speaker"], "shubh")
        self.assertEqual(kwargs["json"]["model"], "bulbul:v3")

    @patch("requests.post")
    def test_sarvam_stt_auth_failure(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_post.return_value = mock_resp

        p = SarvamVoiceProvider(api_key="bad_key")
        with self.assertRaises(STTError) as ctx:
            p.transcribe(b"dummy audio" * 20)
        self.assertIn("authentication failed", str(ctx.exception))

    def test_indic_conformer_retired(self):
        p = IndicConformerVoiceProvider()
        self.assertEqual(p.name, "indicconformer")
        self.assertFalse(p.is_configured())
        self.assertEqual(p.health()["status"], "retired")
        with self.assertRaises(STTError) as ctx:
            p.transcribe(b"test" * 50)
        self.assertIn("retired", str(ctx.exception))


class TestGroundedAssistant(unittest.TestCase):
    def test_forecast_loading(self):
        data = load_forecast_for_area("KGIS-H-180901")
        self.assertIsNotNone(data)
        self.assertIn("forecast", data)
        self.assertIn("p_dry7", data["forecast"])

    def test_question_1_rain_tomorrow(self):
        # 1. "ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?"
        res = generate_grounded_answer("ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?", lang="kn", area_id="KGIS-H-180901")
        self.assertEqual(res["action"], "rain_tomorrow")
        self.assertIn("ನಾಳೆ", res["reply_text"])
        self.assertIn("verdict", res["grounding_data"])

    def test_question_2_rain_this_week(self):
        # 2. "ಈ ವಾರ ಮಳೆ ಹೇಗಿರುತ್ತದೆ?"
        res = generate_grounded_answer("ಈ ವಾರ ಮಳೆ ಹೇಗಿರುತ್ತದೆ?", lang="kn", area_id="KGIS-H-180901")
        self.assertEqual(res["action"], "rain_week")
        self.assertIn("ವಾರ", res["reply_text"])
        self.assertIn("ten_years", res["grounding_data"])

    def test_question_3_heavy_rain_action(self):
        # 3. "ಮಳೆ ಜಾಸ್ತಿ ಆದರೆ ನಾನು ಏನು ಮಾಡಬೇಕು?"
        res = generate_grounded_answer("ಮಳೆ ಜಾಸ್ತಿ ಆದರೆ ನಾನು ಏನು ಮಾಡಬೇಕು?", lang="kn", area_id="KGIS-H-180901")
        self.assertEqual(res["action"], "heavy_rain_action")
        self.assertIn("ಕಾಲುವೆ", res["reply_text"])  # CRIDA drainage advice
        self.assertEqual(res["grounding_data"]["rule_id"], "heavyrain.drainage")

    def test_question_4_crop_watering(self):
        # 4. "ನನ್ನ ಬೆಳೆಗೆ ನೀರು ಹಾಕಬೇಕಾ?"
        res = generate_grounded_answer("ನನ್ನ ಬೆಳೆಗೆ ನೀರು ಹಾಕಬೇಕಾ?", lang="kn", area_id="KGIS-H-180901")
        self.assertEqual(res["action"], "crop_watering")
        self.assertTrue("ನೀರಾವರಿ" in res["reply_text"] or "ನೀರು" in res["reply_text"])

    def test_rain_reporting_intents(self):
        res_yes = generate_grounded_answer("ನಿನ್ನೆ ಜೋರು ಮಳೆ ಬಂತು", lang="kn")
        self.assertEqual(res_yes["action"], "rain_yes")
        self.assertIn("ದಾಖಲಾಗಿದೆ", res_yes["reply_text"])

        res_no = generate_grounded_answer("ಮಳೆ ಬರಲಿಲ್ಲ", lang="kn")
        self.assertEqual(res_no["action"], "rain_no")
        self.assertIn("ದಾಖಲಾಗಿದೆ", res_no["reply_text"])

    def test_sowing_advisory_intent(self):
        res = generate_grounded_answer("ಬಿತ್ತನೆ ಸಲಹೆ ಏನು?", lang="kn", area_id="KGIS-H-180901")
        self.assertEqual(res["action"], "advisory")
        self.assertTrue(len(res["reply_text"]) > 10)

    def test_repeat_intent(self):
        res = generate_grounded_answer("ಮತ್ತೊಮ್ಮೆ ಹೇಳಿ", lang="kn")
        self.assertEqual(res["action"], "repeat")

    def test_multilingual_answers(self):
        for lang, query in [
            ("hi", "कल बारिश होगी क्या?"),
            ("te", "రేపు వర్షం వస్తుందా?"),
            ("en", "will it rain tomorrow?"),
        ]:
            res = generate_grounded_answer(query, lang=lang, area_id="KGIS-H-180901")
            self.assertEqual(res["action"], "rain_tomorrow")
            self.assertTrue(len(res["reply_text"]) > 0)


class TestVoiceServerLogic(unittest.TestCase):
    @patch("services.voice.providers.SarvamVoiceProvider.synthesize")
    @patch("services.voice.providers.SarvamVoiceProvider.transcribe")
    def test_tts_failure_preserves_text_answer(self, mock_transcribe, mock_synthesize):
        """Requirement 7: If STT succeeds but TTS fails, still display the text answer."""
        from services.voice.providers import STTResult

        mock_transcribe.return_value = STTResult(
            transcript="ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?",
            language_code="kn-IN",
            provider="sarvam",
        )
        # TTS fails
        mock_synthesize.side_effect = TTSError("Sarvam TTS service unavailable")

        p = SarvamVoiceProvider(api_key="mock_key")
        stt_res = p.transcribe(b"dummy_audio" * 20, lang="kn")
        self.assertEqual(stt_res.transcript, "ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?")

        # VarshaDrishti assistant generates text
        ans = generate_grounded_answer(stt_res.transcript, lang="kn", area_id="KGIS-H-180901")
        self.assertTrue(len(ans["reply_text"]) > 0)
        self.assertEqual(ans["action"], "rain_tomorrow")

        # TTS fails gracefully
        with self.assertRaises(TTSError):
            p.synthesize(ans["reply_text"], lang="kn")

        # The text answer remains completely preserved and valid!
        self.assertIn("ನಾಳೆ", ans["reply_text"])

    def test_voice_handler_health_endpoint(self):
        from services.voice.server import VoiceHandler
        import io

        class DummyHandler(VoiceHandler):
            def __init__(self):
                self.path = "/health"
                self.headers = {}
                self.rfile = io.BytesIO()
                self.wfile = io.BytesIO()
                self._headers_sent = []
                self.response_code = 0

            def send_response(self, code, message=None):
                self.response_code = code

            def send_header(self, keyword, value):
                self._headers_sent.append((keyword, value))

            def end_headers(self):
                pass

        h = DummyHandler()
        h.do_GET()
        self.assertEqual(h.response_code, 200)
        res = json.loads(h.wfile.getvalue().decode("utf-8"))
        self.assertEqual(res["status"], "ok")
        self.assertIn("provider", res)
        self.assertIn("langs", res)

    def test_voice_handler_interpret_endpoint(self):
        from services.voice.server import VoiceHandler
        import io

        body = json.dumps({
            "transcript": "ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?",
            "lang": "kn",
            "area_id": "KGIS-H-180901",
        }).encode("utf-8")

        class DummyHandler(VoiceHandler):
            def __init__(self):
                self.path = "/interpret"
                self.headers = {"Content-Length": str(len(body)), "Content-Type": "application/json"}
                self.rfile = io.BytesIO(body)
                self.wfile = io.BytesIO()
                self.response_code = 0

            def send_response(self, code, message=None):
                self.response_code = code

            def send_header(self, keyword, value):
                pass

            def end_headers(self):
                pass

        h = DummyHandler()
        h.do_POST()
        self.assertEqual(h.response_code, 200)
        res = json.loads(h.wfile.getvalue().decode("utf-8"))
        self.assertEqual(res["transcript"], "ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ?")
        self.assertEqual(res["action"], "rain_tomorrow")
        self.assertIn("ನಾಳೆ", res["reply_text"])

    @patch("services.voice.providers.SarvamVoiceProvider.synthesize")
    @patch("services.voice.providers.SarvamVoiceProvider.transcribe")
    def test_voice_handler_transcribe_end_to_end(self, mock_transcribe, mock_synthesize):
        from services.voice.server import VoiceHandler
        from services.voice.providers import STTResult, TTSResult
        import io

        mock_transcribe.return_value = STTResult(
            transcript="ಮಳೆ ಜಾಸ್ತಿ ಆದರೆ ನಾನು ಏನು ಮಾಡಬೇಕು?",
            language_code="kn-IN",
            provider="sarvam",
        )
        mock_synthesize.return_value = TTSResult(
            audio_bytes=b"MOCK_SYNTH_AUDIO",
            content_type="audio/wav",
            provider="sarvam",
            language_code="kn-IN",
        )

        audio_data = b"RIFF" + b"\x00" * 300
        boundary = "---------------------------974767299852498929531610575"
        multipart_body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="recording.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8") + audio_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

        class DummyHandler(VoiceHandler):
            def __init__(self):
                self.path = "/transcribe"
                self.headers = {
                    "Content-Length": str(len(multipart_body)),
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "X-Lang": "kn",
                    "X-Area-Id": "KGIS-H-180901",
                }
                self.rfile = io.BytesIO(multipart_body)
                self.wfile = io.BytesIO()
                self.response_code = 0

            def send_response(self, code, message=None):
                self.response_code = code

            def send_header(self, keyword, value):
                pass

            def end_headers(self):
                pass

        with patch.dict(os.environ, {"SARVAM_API_KEY": "dummy_test_key"}):
            h = DummyHandler()
            h.do_POST()
            self.assertEqual(h.response_code, 200)
            res = json.loads(h.wfile.getvalue().decode("utf-8"))
            self.assertEqual(res["transcript"], "ಮಳೆ ಜಾಸ್ತಿ ಆದರೆ ನಾನು ಏನು ಮಾಡಬೇಕು?")
            self.assertEqual(res["action"], "heavy_rain_action")
            self.assertIn("ಕಾಲುವೆ", res["reply_text"])
            self.assertIsNotNone(res["audio_base64"])
            decoded_audio = base64.b64decode(res["audio_base64"])
            self.assertEqual(decoded_audio, b"MOCK_SYNTH_AUDIO")


class TestNarrationBuilder(unittest.TestCase):
    def setUp(self):
        self.data = load_forecast_for_area("KGIS-H-180901")

    def test_build_today_narration_kannada(self):
        from services.voice.narration import build_today_narration
        text = build_today_narration(self.data, lang="kn")
        self.assertIn("Kasaba", text)
        self.assertIn("Tumakuru", text)
        self.assertIn("ಕಳೆದ 10 ವರ್ಷಗಳಲ್ಲಿ", text)
        self.assertIn("ಮಳೆಯ", text)

    def test_build_why_narration_kannada(self):
        from services.voice.narration import build_why_narration
        text = build_why_narration(self.data, lang="kn")
        self.assertIn("ಮಳೆ ದಾಖಲೆ", text)
        self.assertIn("34 ವರ್ಷಗಳ", text)
        self.assertIn("ಐಸಿಎಆರ್-ಕ್ರಿಡಾ", text)

    def test_build_today_narration_english(self):
        from services.voice.narration import build_today_narration
        text = build_today_narration(self.data, lang="en")
        self.assertIn("Kasaba, Tumakuru", text)
        self.assertIn("In 5 of the last 10 years", text)

    def test_build_why_narration_english(self):
        from services.voice.narration import build_why_narration
        text = build_why_narration(self.data, lang="en")
        self.assertIn("34 years of IMD rainfall", text)
        self.assertIn("ICAR-CRIDA", text)


class TestAudioCache(unittest.TestCase):
    def test_deterministic_cache_path(self):
        from services.voice.server import _audio_cache_path
        p1 = _audio_cache_path("sarvam", "kn", "ನಮಸ್ಕಾರ")
        p2 = _audio_cache_path("sarvam", "kn", "ನಮಸ್ಕಾರ")
        self.assertEqual(p1, p2)
        self.assertTrue(str(p1).endswith(".wav"))


if __name__ == "__main__":
    unittest.main()
