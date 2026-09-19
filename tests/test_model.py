import copy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
import threading
import time
import unittest
from unittest.mock import Mock, patch

from jev_ios.model import JevModel, MODEL, ModelError, ModelOptions, build_questions, parse_decision


def answer(choice, probabilities):
    return {"type": "choice", "choice": choice, "probabilities": probabilities}


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.questions = build_questions(
            {"TAP": "Tap a control", "TYPE_TEXT": "Type supplied text", "DONE": "Goal complete"},
            {"1": "Search", "2": "Continue"},
            {"3": "First name", "4": "Last name"},
            {"first": "Alice", "last": "Example"},
        )
        self.response = {
            "model": MODEL,
            "answers": {
                "operation": answer("TAP", {"TAP": 0.9, "TYPE_TEXT": 0.05, "DONE": 0.05}),
                "tap_target": answer("2", {"1": 0.1, "2": 0.9}),
            },
            "usage": {"inputTokens": 100, "outputTokens": 10},
        }

    def test_tap_uses_only_compatible_head(self):
        self.response["answers"]["type_text_target"] = {"choice": "injected"}
        self.response["answers"]["text_value:3"] = {"choice": "injected"}
        decision = parse_decision(self.response, self.questions, model_ms=12)
        self.assertEqual(decision["target"], "2")
        self.assertEqual(decision["model"], MODEL)
        self.assertEqual(decision["model_ms"], 12)
        self.assertNotIn("text_key", decision)

    def test_type_uses_selected_fields_text_head(self):
        self.response["answers"].update({
            "operation": answer("TYPE_TEXT", {"TAP": 0.02, "TYPE_TEXT": 0.96, "DONE": 0.02}),
            "type_text_target": answer("4", {"3": 0.05, "4": 0.95}),
            "text_value:3": {"malformed_unused_answer": True},
            "text_value:4": answer("last", {"first": 0.1, "last": 0.9}),
        })
        decision = parse_decision(self.response, self.questions)
        self.assertEqual((decision["target"], decision["text_key"]), ("4", "last"))
        self.assertEqual(decision["probability"], 0.9)

    def test_done_cannot_execute_speculative_target(self):
        self.response["answers"]["operation"] = answer("DONE", {"TAP": 0.01, "TYPE_TEXT": 0.01, "DONE": 0.98})
        decision = parse_decision(self.response, self.questions)
        self.assertNotIn("target", decision)
        self.assertNotIn("text_key", decision)

    def test_invalid_selected_ids(self):
        for head in ("operation", "tap_target"):
            with self.subTest(head=head):
                response = copy.deepcopy(self.response)
                response["answers"][head]["choice"] = "not-observed"
                with self.assertRaises(ModelError):
                    parse_decision(response, self.questions)

    def test_invalid_probability_values(self):
        for value in (math.nan, math.inf, -0.1, 1.1, True, "0.1"):
            with self.subTest(value=value):
                response = copy.deepcopy(self.response)
                response["answers"]["tap_target"]["probabilities"]["1"] = value
                with self.assertRaises(ModelError):
                    parse_decision(response, self.questions)

    def test_missing_extra_or_inconsistent_probabilities(self):
        for probabilities in ({"2": 1}, {"1": 0.1, "2": 0.8, "extra": 0.1}, {"1": 0.1, "2": 0.1}, {"1": 0.9, "2": 0.1}):
            with self.subTest(probabilities=probabilities):
                response = copy.deepcopy(self.response)
                response["answers"]["tap_target"]["probabilities"] = probabilities
                with self.assertRaises(ModelError):
                    parse_decision(response, self.questions)

    def test_operation_and_target_head_must_match(self):
        self.response["answers"].pop("tap_target")
        self.response["answers"]["type_text_target"] = answer("3", {"3": 0.9, "4": 0.1})
        with self.assertRaises(ModelError):
            parse_decision(self.response, self.questions)

    def test_wrong_model_and_missing_envelope_fail(self):
        for response in ({"model": "other", "answers": {}}, {"model": MODEL}, None):
            with self.subTest(response=response), self.assertRaises(ModelError):
                parse_decision(response, self.questions)

    def test_no_text_values_removes_type_operation(self):
        questions = build_questions({"TYPE_TEXT": "Type", "DONE": "Done"}, {}, {"1": "Field"}, {})
        self.assertEqual(questions["operation"]["criteria"], {"DONE": "Done"})
        self.assertEqual(set(questions), {"operation"})

    def test_no_targets_removes_corresponding_operations(self):
        questions = build_questions({"TAP": "Tap", "TYPE_TEXT": "Type", "DONE": "Done"}, {}, {}, {"x": "Value"})
        self.assertEqual(questions["operation"]["criteria"], {"DONE": "Done"})

    def test_generated_text_is_never_accepted(self):
        self.response["answers"].update({
            "operation": answer("TYPE_TEXT", {"TAP": 0, "TYPE_TEXT": 1, "DONE": 0}),
            "type_text_target": answer("4", {"3": 0, "4": 1}),
            "text_value:4": answer("invented-value", {"first": 0, "last": 1}),
        })
        with self.assertRaises(ModelError):
            parse_decision(self.response, self.questions)


class ClientTests(unittest.TestCase):
    def test_slow_connect_returns_by_deadline_and_never_sends_late_request(self):
        release = threading.Event()
        late_closed = threading.Event()
        connection = Mock(sock=None)
        def connect():
            release.wait(1)
            connection.sock = Mock()
        def close():
            if connection.sock is not None:
                late_closed.set()
        connection.connect.side_effect = connect
        connection.close.side_effect = close
        try:
            with patch("jev_ios.model.http.client.HTTPSConnection", return_value=connection):
                model = JevModel(ModelOptions(timeout_seconds=0.05), api_key="fixture-key")
                started = time.monotonic()
                with self.assertRaisesRegex(ModelError, "connection failed or timed out"):
                    model.decide({}, {"DONE": "Done"}, {}, {}, {})
                self.assertLess(time.monotonic() - started, 0.25)
                self.assertEqual(model.calls, 1)
                self.assertIsNone(model._connection)
                connection.request.assert_not_called()
        finally:
            release.set()
        self.assertTrue(late_closed.wait(0.5))
        connection.request.assert_not_called()

    def test_oidc_environment_fallback(self):
        response = {"model": MODEL, "answers": {"operation": answer("DONE", {"DONE": 1})}}
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read1 = io.BytesIO(json.dumps(response).encode()).read1
        with patch.dict("os.environ", {"VERCEL_OIDC_TOKEN": "test-oidc-token"}, clear=True):
            with patch("jev_ios.model.http.client.HTTPSConnection", return_value=connection):
                with JevModel() as model:
                    model.decide({}, {"DONE": "Done"}, {}, {}, {})
        self.assertEqual(connection.request.call_args.kwargs["headers"]["Authorization"], "Bearer test-oidc-token")

    def test_missing_credential_is_checked_before_network(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("jev_ios.model.http.client.HTTPSConnection") as connection:
                with self.assertRaisesRegex(ModelError, "AI_GATEWAY_API_KEY or VERCEL_OIDC_TOKEN"):
                    JevModel().decide({}, {"DONE": "Done"}, {}, {}, {})
                connection.assert_not_called()

    def test_options_are_bounded(self):
        for options in ({"max_calls": 31}, {"max_calls": 0}, {"max_request_bytes": 24001}, {"timeout_seconds": math.inf}, {"timeout_seconds": 31}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                ModelOptions(**options)

    def test_request_size_is_checked_before_network(self):
        model = JevModel(api_key="test-key")
        with patch("jev_ios.model.http.client.HTTPSConnection") as connection:
            with self.assertRaises(ModelError):
                model.decide({"text": "a" * 24000}, {"DONE": "Done"}, {}, {}, {})
            connection.assert_not_called()
        self.assertEqual(model.calls, 0)

    def test_persistent_connection_and_call_budget(self):
        response = {"model": MODEL, "answers": {"operation": answer("DONE", {"DONE": 1})}}
        connection = Mock()
        def getresponse():
            body = Mock(status=200)
            body.read1 = io.BytesIO(json.dumps(response).encode()).read1
            return body
        connection.getresponse.side_effect = getresponse
        with patch("jev_ios.model.http.client.HTTPSConnection", return_value=connection) as constructor:
            with JevModel(ModelOptions(max_calls=2), api_key="test-key") as model:
                for _ in range(2):
                    model.decide({"goal": "Done"}, {"DONE": "Done"}, {}, {}, {})
                with self.assertRaises(ModelError):
                    model.decide({}, {"DONE": "Done"}, {}, {}, {})
                self.assertEqual(model.calls, 2)
                constructor.assert_called_once()
                self.assertEqual(connection.request.call_count, 2)
                call = connection.request.call_args
                self.assertEqual(call.args, ("POST", "/v1/evaluate"))
                self.assertEqual(json.loads(call.kwargs["body"])["model"], MODEL)
            connection.close.assert_called_once()

    def test_trickling_body_and_headers_obey_one_wall_deadline(self):
        payload = json.dumps({"model": MODEL, "answers": {"operation": answer("DONE", {"DONE": 1})}}).encode()
        for phase in ("body", "headers", "fast-close"):
            with self.subTest(phase=phase):
                requests = []
                class Handler(BaseHTTPRequestHandler):
                    protocol_version = "HTTP/1.1"

                    def log_message(self, *_args):
                        pass

                    def do_POST(self):
                        self.close_connection = True
                        self.rfile.read(int(self.headers.get("Content-Length", "0")))
                        requests.append(self.path)
                        try:
                            if phase == "headers":
                                self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                                self.wfile.flush()
                                for i in range(10):
                                    time.sleep(0.04)
                                    self.wfile.write(f"X-Fixture-{i}: ok\r\n".encode())
                                    self.wfile.flush()
                                self.wfile.write(f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)
                            else:
                                self.send_response(200)
                                self.send_header("Content-Length", str(len(payload)))
                                if phase == "fast-close":
                                    self.send_header("Connection", "close")
                                self.end_headers()
                                for offset in range(0, len(payload), 15):
                                    self.wfile.write(payload[offset:offset + 15])
                                    self.wfile.flush()
                                    if phase != "fast-close":
                                        time.sleep(0.04)
                        except (BrokenPipeError, ConnectionResetError):
                            pass

                server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                server.daemon_threads = True
                worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
                worker.start()
                try:
                    factory = lambda _host, timeout: http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=timeout)
                    with patch("jev_ios.model.http.client.HTTPSConnection", side_effect=factory):
                        model = JevModel(ModelOptions(timeout_seconds=0.12, max_calls=1), api_key="fixture-key")
                        started = time.monotonic()
                        if phase == "fast-close":
                            self.assertEqual(model.decide({}, {"DONE": "Done"}, {}, {}, {})["operation"], "DONE")
                            model.close()
                        else:
                            with self.assertRaisesRegex(ModelError, "connection failed or timed out"):
                                model.decide({}, {"DONE": "Done"}, {}, {}, {})
                        self.assertLess(time.monotonic() - started, 0.4)
                        self.assertEqual(requests, ["/v1/evaluate"])
                        self.assertEqual(model.calls, 1)
                        self.assertIsNone(model._connection)
                finally:
                    server.shutdown()
                    server.server_close()
                    worker.join(timeout=1)

    def test_http_error_does_not_retry_or_expose_body(self):
        connection = Mock()
        connection.getresponse.return_value.status = 429
        connection.getresponse.return_value.read.return_value = b"secret response"
        with patch("jev_ios.model.http.client.HTTPSConnection", return_value=connection):
            model = JevModel(api_key="private-test-key")
            with self.assertRaises(ModelError) as error:
                model.decide({}, {"DONE": "Done"}, {}, {}, {})
            self.assertEqual(str(error.exception), "Jev provider returned HTTP 429; no action dispatched for this decision.")
            self.assertEqual(connection.request.call_count, 1)
            connection.getresponse.return_value.read.assert_not_called()

    def test_connection_error_is_sanitized_and_consumes_budget(self):
        connection = Mock()
        connection.request.side_effect = OSError("private response or credential")
        with patch("jev_ios.model.http.client.HTTPSConnection", return_value=connection):
            model = JevModel(ModelOptions(max_calls=1), api_key="private-test-key")
            with self.assertRaisesRegex(ModelError, "connection failed or timed out"):
                model.decide({}, {"DONE": "Done"}, {}, {}, {})
            self.assertEqual(model.calls, 1)
            connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
