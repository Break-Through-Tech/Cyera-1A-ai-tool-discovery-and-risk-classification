"""Offline Streamlit tests with a small model stub and guarded Gemini client."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from google.genai import errors
from streamlit.testing.v1 import AppTest

from rag_bot import semantic
from rag_bot.generator import GeminiSettings, GenerationError
from rag_bot.test_semantic import WordTokenizer


class LocalModel:
    tokenizer = WordTokenizer()
    max_seq_length = 256

    def get_embedding_dimension(self):
        return 2

    def encode(self, texts, **kwargs):
        return [
            [0, 1] if text == "No evidence?" or text.startswith("Fictional Compass") else [1, 0]
            for text in texts
        ]


class AppTests(TestCase):
    def setUp(self):
        cache = TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        root = Path(cache.name)
        cache_patch = patch("rag_bot.vector_store.CACHE_DIR", root)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        model = patch("rag_bot.semantic.load_model", return_value=LocalModel())
        self.load_model = model.start()
        self.addCleanup(model.stop)
        client = patch("rag_bot.generator.genai.Client", side_effect=AssertionError("Unexpected Gemini"))
        self.client = client.start()
        self.addCleanup(client.stop)
        clear_cache = patch.object(semantic, "MODEL_REVISION", self.id())
        clear_cache.start()
        self.addCleanup(clear_cache.stop)
        self.app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
        self.assertFalse(self.app.exception)

    def mode(self, name):
        self.app.selectbox[0].select(name).run()
        self.assertFalse(self.app.exception)

    def ask(self, question):
        self.app.chat_input[0].set_value(question).run()
        self.assertFalse(self.app.exception)

    def click(self, label):
        next(button for button in self.app.button if button.label == label).click().run()
        self.assertFalse(self.app.exception)

    def test_default_semantic_and_local_question(self):
        self.assertEqual(self.app.title[0].value, "AI Governance Assistant")
        self.assertEqual(self.app.selectbox[0].value, "Semantic Search")
        self.assertEqual(self.app.number_input[0].value, 0.25)
        self.assertIn("Embedding dimension: 2", [text.value for text in self.app.text])
        self.ask("What is a Tool Candidate?")
        self.assertEqual(len(self.app.session_state["turns"]), 1)
        self.assertTrue(any("Cosine similarity" in expander.label for expander in self.app.expander))
        self.assertTrue(any("Chunk ID:" in text.value for text in self.app.text))
        self.app.toggle[1].set_value(True).run()
        self.assertTrue(any(expander.label == "Retrieval diagnostics" for expander in self.app.expander))
        self.load_model.assert_called_once()
        self.client.assert_not_called()

    def test_keyword_switch_keeps_old_mode_and_clear(self):
        self.ask("What is a Tool Candidate?")
        self.mode("Keyword Search")
        self.ask("What is a Tool Candidate?")
        self.app.run()
        turns = self.app.session_state["turns"]
        self.assertEqual([turn.mode for turn in turns], ["Semantic Search", "Keyword Search"])
        self.assertTrue(any("Keyword score" in expander.label for expander in self.app.expander))
        self.click("Clear conversation")
        self.assertEqual(len(self.app.chat_message), 0)
        self.client.assert_not_called()

    def test_empty_evidence_and_blank_input(self):
        self.ask("   ")
        self.assertEqual(len(self.app.chat_message), 0)
        self.ask("No evidence?")
        self.assertTrue(any("No relevant evidence" in item.value for item in self.app.info))
        self.assertEqual(self.app.session_state["turns"][0].matches, ())
        self.client.assert_not_called()

    def test_demo_citation_and_suggested_question_only_submits_once(self):
        self.mode("Demo — Mock Generation")
        self.click("What is a Tool Candidate?")
        self.app.run()
        turn, = self.app.session_state["turns"]
        self.assertEqual(turn.answer.status, "partial")
        self.assertEqual(turn.answer.cited_sources[0].chunk, turn.matches[0].chunk)
        self.assertTrue(any("Citation 1" in expander.label for expander in self.app.expander))
        self.assertTrue(any("Simulated response" in item.value for item in self.app.info))
        self.app.toggle[0].set_value(False).run()
        self.assertFalse(any("Citation 1" in expander.label for expander in self.app.expander))
        self.client.assert_not_called()

    def test_missing_gemini_credentials(self):
        with patch("rag_bot.generator.load_settings", side_effect=GenerationError("Set GEMINI_API_KEY.")):
            self.mode("RAG — Gemini")
            self.assertTrue(self.app.chat_input[0].disabled)
            self.assertTrue(any("Set GEMINI_API_KEY" in item.value for item in self.app.warning))
        self.mode("Semantic Search")
        self.assertFalse(self.app.chat_input[0].disabled)
        self.client.assert_not_called()

    def test_gemini_requires_opt_in_and_reports_billing_error(self):
        self.client.side_effect = None
        request = self.client.return_value.models.generate_content
        request.side_effect = errors.ClientError(
            402, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "private diagnostic"}}
        )
        with patch("rag_bot.generator.load_settings",
                   return_value=GeminiSettings("gemini-3.5-flash-lite", "test-only")):
            self.mode("RAG — Gemini")
            self.assertTrue(self.app.chat_input[0].disabled)
            self.client.assert_not_called()
            self.app.checkbox[0].check().run()
            self.assertFalse(self.app.chat_input[0].disabled)
            self.ask("What is a Tool Candidate?")
        request.assert_called_once()
        self.client.return_value.close.assert_called_once()
        error = self.app.error[0].value
        self.assertIn("HTTP 402", error)
        self.assertNotIn("private diagnostic", error)
        self.assertIsNone(self.app.session_state["turns"][0].answer)

    def test_embedding_failure_keeps_keyword_available(self):
        with patch("rag_bot.semantic.SemanticRetriever.from_snapshot", side_effect=ValueError("model unavailable")):
            with patch.object(semantic, "MODEL_REVISION", "broken-model"):
                self.app.run()
                self.assertTrue(self.app.chat_input[0].disabled)
                self.assertTrue(any("Keyword Search is still available" in item.value
                                    for item in self.app.warning))
                self.mode("Keyword Search")
                self.ask("What is a Tool Candidate?")
                self.assertTrue(self.app.session_state["turns"][0].matches)
        self.client.assert_not_called()

    def test_profile_gates_and_cache_switching_preserve_turn_provenance(self):
        from rag_bot.test_catalog import csv_bytes, fictional_profile, row

        self.assertEqual(self.app.selectbox[1].value, "docs_only")
        self.ask("What is a Tool Candidate?")
        original, = self.app.session_state["turns"]
        self.app.selectbox[1].select("catalog_unseen_eval").run()
        self.assertTrue(self.app.chat_input[0].disabled)
        self.assertTrue(any("checksum" in warning.value for warning in self.app.warning))
        self.app.selectbox[1].select("catalog_dev").run()
        self.assertTrue(self.app.chat_input[0].disabled)
        self.assertTrue(any("reuse permission" in warning.value for warning in self.app.warning))

        with fictional_profile(row()) as path:
            self.app.run()
            self.assertFalse(self.app.chat_input[0].disabled)
            self.assertIn("Loaded passages: 8", [item.value for item in self.app.text])
            self.mode("Keyword Search")
            self.ask("Fictional Compass")
            catalog_turn = self.app.session_state["turns"][-1]
            self.assertEqual(catalog_turn.matches[0].passage.source_role, "tool_evidence")
            self.assertTrue(any("Hostname: compass.example" in item.value for item in self.app.text))
            path.write_bytes(csv_bytes(row(**{"Short Description": "New fictional evidence."})))
            self.mode("Semantic Search")
            self.ask("Fictional Compass")
            edited = self.app.session_state["turns"][-1]
            self.assertNotEqual(edited.corpus_version, catalog_turn.corpus_version)
            index = next(match for match in edited.matches if match.chunk.passage.catalog)
            self.assertEqual(index.chunk.text, "New fictional evidence.")
            self.mode("RAG — Gemini")
            self.assertTrue(self.app.chat_input[0].disabled)
            self.assertTrue(any("only for docs_only" in item.value for item in self.app.warning))
        self.assertEqual(self.app.session_state["turns"][0], original)
        self.assertEqual(original.corpus_profile, "docs_only")
        self.assertEqual(edited.corpus_profile, "catalog_dev")
        self.load_model.assert_called_once()
        self.client.assert_not_called()

    def test_rebuild_and_memory_only_index_controls(self):
        self.assertTrue(any("newly built" in item.value for item in self.app.caption))
        self.click("Rebuild current index")
        self.assertTrue(any("newly built" in item.value for item in self.app.caption))
        self.app.run()
        self.assertTrue(any("loaded from disk" in item.value for item in self.app.caption))
        next(toggle for toggle in self.app.toggle
             if toggle.label == "Persistent vector cache").set_value(False).run()
        self.assertTrue(any("memory-only" in item.value for item in self.app.caption))
        self.client.assert_not_called()

    def test_hybrid_mode_and_demo_keep_strategy_and_reuse_vectors(self):
        self.mode("Hybrid Search")
        self.ask("What is a Tool Candidate?")
        first, = self.app.session_state["turns"]
        self.assertEqual(first.strategy, "hybrid")
        self.assertEqual(first.hybrid_config.smoothing, 60)
        with patch.object(semantic.SemanticRetriever, "from_snapshot",
                          wraps=semantic.SemanticRetriever.from_snapshot) as build:
            next(number for number in self.app.number_input
                 if number.label == "RRF smoothing").set_value(42).run()
            self.ask("How is contextual risk evaluated?")
            build.assert_not_called()
        self.assertEqual([turn.hybrid_config.smoothing for turn in self.app.session_state["turns"]],
                         [60, 42])
        self.app.toggle[1].set_value(True).run()
        self.assertTrue(any("Semantic rank" in item.value for item in self.app.text))
        self.mode("Demo — Mock Generation")
        self.app.selectbox[2].select("hybrid").run()
        self.ask("What is a Tool Candidate?")
        turn = self.app.session_state["turns"][-1]
        self.assertEqual(turn.strategy, "hybrid")
        self.assertTrue(turn.answer.cited_sources)
        self.assertEqual(self.app.session_state["turns"][0], first)
        self.load_model.assert_called_once()
        self.client.assert_not_called()

    def test_preset_change_keeps_old_turn_and_current_index(self):
        self.mode("Hybrid Search")
        self.ask("What is a Tool Candidate?")
        original, = self.app.session_state["turns"]
        with patch.object(semantic.SemanticRetriever, "from_snapshot") as build:
            next(box for box in self.app.selectbox
                 if box.label == "Retrieval preset").select("hybrid-calibrated").run()
            self.ask("What is a Tool Candidate?")
            build.assert_not_called()
        turns = self.app.session_state["turns"]
        self.assertEqual(turns[0], original)
        self.assertEqual(original.preset, "Hybrid — Baseline")
        self.assertEqual(turns[1].preset, "Hybrid — Calibrated (experimental)")
        self.assertIsNone(turns[1].hybrid_config.max_per_passage)
        self.assertEqual(turns[1].hybrid_config.smoothing, 10)
        self.assertTrue(any(tab.label == "Retrieval evaluation" for tab in self.app.tabs))
        self.client.assert_not_called()

    def test_semantic_turn_records_and_displays_its_result_limit(self):
        self.ask("What is a Tool Candidate?")
        turn, = self.app.session_state["turns"]
        self.assertEqual(turn.strategy, "semantic")
        self.assertEqual(turn.result_limit, 5)
        self.assertIn("Result limit: 5", [item.value for item in self.app.text])
        self.mode("Hybrid Search")
        self.assertEqual(self.app.session_state["turns"][0].result_limit, 5)
