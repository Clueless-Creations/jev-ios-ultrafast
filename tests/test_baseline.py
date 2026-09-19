import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
import threading
import time
import unittest
from unittest.mock import Mock, patch

from jev_ios.baseline import ChatCompletionModel, MAX_OUTPUT_TOKENS, build_request, parse_decision
from jev_ios.model import HOST, ModelError, ModelOptions, build_questions


MODEL = "openai/gpt-5.4-nano"
ACTIONS = {"TAP": "Tap one control", "TYPE_TEXT": "Type supplied text", "WAIT": "Wait", "DONE": "Goal complete"}
TAPS = {"1": "Search", "2": "Continue"}
FIELDS = {"3": "First name", "4": "Last name"}
TEXTS = {"first": "Alice", "last": "Example"}


def completion(operation="TAP", target="2", text_key=None):
    return {
        "model": MODEL,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps({"operation": operation, "target": target, "text_key": text_key}),
            "refusal": None,
        }}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 24, "total_tokens": 144, "prompt_tokens_details": {"cached_tokens": 100}},
    }


def connection_for(response=None):
    connection = Mock()
    def getresponse():
        body = Mock(status=200)
        body.read1 = io.BytesIO(json.dumps(response if response is not None else completion()).encode()).read1
        return body
    connection.getresponse.side_effect = getresponse
    return connection


class BaselineRequestTests(unittest.TestCase):
    def test_same_state_and_choice_maps_as_jev(self):
        state = {"goal": "Search", "screen": {"controls": [{"id": "2", "label": "Continue"}]}, "recent_actions": []}
        request, space = build_request(MODEL, state, ACTIONS, TAPS, FIELDS, TEXTS)
        content = json.loads(request["messages"][1]["content"])
        self.assertEqual(content, {"state": state, "actions": ACTIONS, "tap_targets": TAPS, "type_targets": FIELDS, "text_values": TEXTS})
        self.assertEqual(space["actions"], build_questions(ACTIONS, TAPS, FIELDS, TEXTS)["operation"]["criteria"])
        self.assertEqual(request["model"], MODEL)
        self.assertEqual(request["reasoning_effort"], "none")
        self.assertEqual(request["temperature"], 0)
        self.assertEqual(request["max_tokens"], MAX_OUTPUT_TOKENS)
        self.assertFalse(request["stream"])

    def test_strict_schema_only_exposes_offered_keys(self):
        request, _ = build_request(MODEL, {}, ACTIONS, TAPS, FIELDS, TEXTS)
        output = request["response_format"]
        self.assertEqual(output["type"], "json_schema")
        self.assertTrue(output["json_schema"]["strict"])
        schema = output["json_schema"]["schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["properties"]), {"operation", "target", "text_key"})
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertEqual(schema["properties"]["target"]["enum"], ["1", "2", "3", "4", None])
        self.assertEqual(schema["properties"]["text_key"]["enum"], ["first", "last", None])

    def test_unavailable_actions_removed_identically(self):
        for taps, fields, texts in (({}, FIELDS, TEXTS), (TAPS, {}, TEXTS), (TAPS, FIELDS, {}), ({}, {}, {})):
            with self.subTest(taps=taps, fields=fields, texts=texts):
                request, space = build_request(MODEL, {}, ACTIONS, taps, fields, texts)
                self.assertEqual(space["actions"], build_questions(ACTIONS, taps, fields, texts)["operation"]["criteria"])
                self.assertEqual(request["response_format"]["json_schema"]["schema"]["properties"]["operation"]["enum"], list(space["actions"]))

    def test_reasoning_parameter_can_be_omitted(self):
        request, _ = build_request(MODEL, {}, ACTIONS, TAPS, {}, {}, reasoning_effort=None)
        self.assertNotIn("reasoning_effort", request)

    def test_astra_requests_omit_temperature_and_reserve_reasoning_tokens(self):
        for model in ("openai/gpt-6-astra", "openai/gpt-6-astra-fast"):
            with self.subTest(model=model):
                request, _ = build_request(model, {}, ACTIONS, TAPS, {}, {})
                self.assertEqual(request["model"], model)
                self.assertNotIn("temperature", request)
                self.assertEqual(request["reasoning_effort"], "low")
                self.assertEqual(request["max_tokens"], 1024)
                self.assertTrue(request["response_format"]["json_schema"]["strict"])
        request, _ = build_request("openai/gpt-6-astra", {}, ACTIONS, TAPS, {}, {}, max_output_tokens=2048)
        self.assertEqual(request["max_tokens"], 2048)

    def test_invalid_model_and_effort_rejected_without_network(self):
        for model in (None, "", "model", "provider/model\nsecret", "https://different-host.test/model", "provider/" + "x" * 201):
            with self.subTest(model=model), self.assertRaises(ValueError):
                ChatCompletionModel(model)
        with self.assertRaises(ValueError):
            ChatCompletionModel(MODEL, reasoning_effort="private-arbitrary-value")


class BaselineDecisionTests(unittest.TestCase):
    def setUp(self):
        _, self.space = build_request(MODEL, {}, ACTIONS, TAPS, FIELDS, TEXTS)

    def parse(self, value, **kwargs):
        return parse_decision(value, self.space, model=MODEL, **kwargs)

    def test_tap_has_no_synthetic_confidence(self):
        result = self.parse(completion(), model_ms=13.2)
        self.assertEqual(result["operation"], "TAP")
        self.assertEqual(result["target"], "2")
        self.assertNotIn("text_key", result)
        self.assertIsNone(result["probability"])
        self.assertEqual(result["confidence_kind"], "not_reported")
        self.assertEqual(result["model"], MODEL)
        self.assertEqual(result["model_ms"], 13.2)

    def test_type_selects_only_supplied_key(self):
        result = self.parse(completion("TYPE_TEXT", "4", "last"))
        self.assertEqual((result["target"], result["text_key"]), ("4", "last"))
        self.assertNotIn("text", result)

    def test_done_wait_have_no_executable_target(self):
        for operation in ("DONE", "WAIT"):
            with self.subTest(operation=operation):
                result = self.parse(completion(operation, None, None))
                self.assertNotIn("target", result)
                self.assertNotIn("text_key", result)

    def test_generated_or_incompatible_choices_rejected(self):
        for operation, target, key in (("DELETE", None, None), ("TAP", "999", None), ("TAP", "3", None),
                                       ("TAP", "2", "last"), ("TYPE_TEXT", "2", "last"), ("TYPE_TEXT", "4", "invented text"),
                                       ("DONE", "2", None), ("WAIT", None, "last"), ("TAP", ["2"], None), ("TYPE_TEXT", "4", {})):
            with self.subTest(operation=operation, target=target, key=key), self.assertRaises(ModelError):
                self.parse(completion(operation, target, key))

    def test_extra_missing_malformed_or_duplicate_decision_properties_rejected(self):
        for content in ('{"operation":"TAP","target":"2"}',
                        '{"operation":"TAP","target":"2","text_key":null,"x":100}',
                        '{"operation":"TAP","operation":"DONE","target":null,"text_key":null}',
                        '```json\n{"operation":"DONE","target":null,"text_key":null}\n```',
                        'not json', 'null', '[]', 'true'):
            response = completion()
            response["choices"][0]["message"]["content"] = content
            with self.subTest(content=content), self.assertRaises(ModelError):
                self.parse(response)

    def test_invalid_envelopes_and_wrong_models_rejected(self):
        for response in (None, [], {}, {"model": "wrong", "choices": []}, {"model": MODEL, "choices": None},
                         {"model": MODEL, "choices": []}, {"model": MODEL, "choices": [None]},
                         {"model": MODEL, "choices": completion()["choices"] * 2}):
            with self.subTest(response=response), self.assertRaises(ModelError):
                self.parse(response)

    def test_refusals_truncation_and_tool_calls_rejected(self):
        mutations = (("finish_reason", "length"), ("finish_reason", "content_filter"), ("finish_reason", "tool_calls"),
                     ("refusal", "private refusal detail"), ("refusal", ""), ("content", None), ("content", []),
                     ("role", "user"), ("tool_calls", [{"function": {"name": "shell"}}]), ("function_call", {"name": "shell"}))
        for key, value in mutations:
            response = completion()
            target = response["choices"][0] if key == "finish_reason" else response["choices"][0]["message"]
            target[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ModelError) as error:
                self.parse(response)
            self.assertNotIn("private refusal detail", str(error.exception))

    def test_usage_preserves_only_valid_counts_and_cache_details(self):
        self.assertEqual(self.parse(completion())["usage"], {"inputTokens": 120, "outputTokens": 24, "totalTokens": 144, "cacheReadInputTokens": 100})
        for usage in (None, [], {"prompt_tokens": True, "completion_tokens": -1, "total_tokens": math.nan},
                      {"prompt_tokens_details": {"cached_tokens": 1}}, {"prompt_tokens": 1, "prompt_tokens_details": {"cached_tokens": 2}}):
            response = completion()
            response["usage"] = usage
            result = self.parse(response)
            self.assertNotIn("cacheReadInputTokens", result["usage"])
            self.assertTrue(all(type(value) is int and value >= 0 for value in result["usage"].values()))

    def test_reasoning_and_cache_write_usage_are_subsets_not_extra_output(self):
        response = completion()
        response["usage"]["prompt_tokens_details"]["cache_write_tokens"] = 20
        response["usage"]["completion_tokens_details"] = {"reasoning_tokens": 16}
        usage = self.parse(response)["usage"]
        self.assertEqual(usage["cacheWriteInputTokens"], 20)
        self.assertEqual(usage["reasoningOutputTokens"], 16)
        self.assertEqual(usage["outputTokens"], 24)
        for invalid in (True, -1, 25):
            response["usage"]["completion_tokens_details"]["reasoning_tokens"] = invalid
            response["usage"]["prompt_tokens_details"]["cache_write_tokens"] = invalid
            usage = self.parse(response)["usage"]
            self.assertNotIn("reasoningOutputTokens", usage)
            self.assertNotIn("cacheWriteInputTokens", usage)


class BaselineClientTests(unittest.TestCase):
    def decide(self, model, state=None):
        return model.decide(state if state is not None else {}, ACTIONS, TAPS, FIELDS, TEXTS)

    def test_astra_transport_uses_profile_without_changing_timeout_or_model_identity(self):
        response = completion()
        response["model"] = "openai/gpt-6-astra-fast"
        connection = connection_for(response)
        with patch("jev_ios.baseline.http.client.HTTPSConnection", return_value=connection) as constructor:
            model = ChatCompletionModel(response["model"], api_key="fixture-key", max_output_tokens=2048)
            result = self.decide(model)
        constructor.assert_called_once_with(HOST, timeout=10.0)
        request = json.loads(connection.request.call_args.kwargs["body"])
        self.assertEqual(request["model"], response["model"])
        self.assertEqual(request["max_tokens"], 2048)
        self.assertEqual(request["reasoning_effort"], "low")
        self.assertNotIn("temperature", request)
        self.assertEqual(result["model"], response["model"])

    def test_fixed_host_persistent_connection_and_call_limit(self):
        connection = connection_for()
        with patch("jev_ios.baseline.http.client.HTTPSConnection", return_value=connection) as constructor:
            with ChatCompletionModel(MODEL, ModelOptions(max_calls=2), api_key="fixture-key") as model:
                self.decide(model)
                self.decide(model)
                with self.assertRaisesRegex(ModelError, "call budget"):
                    self.decide(model)
                self.assertEqual(model.calls, 2)
                constructor.assert_called_once_with(HOST, timeout=10.0)
                self.assertEqual(connection.request.call_count, 2)
                self.assertEqual(connection.request.call_args.args, ("POST", "/v1/chat/completions"))
                request = json.loads(connection.request.call_args.kwargs["body"])
                self.assertEqual(request["max_tokens"], 128)
                self.assertEqual(request["reasoning_effort"], "none")
            connection.close.assert_called_once()

    def test_oidc_fallback_and_optional_reasoning(self):
        connection = connection_for()
        with patch.dict("os.environ", {"VERCEL_OIDC_TOKEN": "fixture-token"}, clear=True), patch("jev_ios.baseline.http.client.HTTPSConnection", return_value=connection):
            with ChatCompletionModel(MODEL, reasoning_effort=None) as model:
                self.decide(model)
        self.assertEqual(connection.request.call_args.kwargs["headers"]["Authorization"], "Bearer fixture-token")
        self.assertNotIn("reasoning_effort", json.loads(connection.request.call_args.kwargs["body"]))

    def test_invalid_credentials_never_reach_network_or_errors(self):
        for key in (None, "", "private\nfixture", "private\x7ffixture", "private fixture"):
            with self.subTest(key=key), patch.dict("os.environ", {}, clear=True), patch("jev_ios.baseline.http.client.HTTPSConnection") as connection:
                model = ChatCompletionModel(MODEL, api_key=key)
                with self.assertRaisesRegex(ModelError, "AI_GATEWAY_API_KEY or VERCEL_OIDC_TOKEN") as error:
                    self.decide(model)
                self.assertNotIn("private", str(error.exception))
                connection.assert_not_called()
                self.assertEqual(model.calls, 0)

    def test_oversized_invalid_state_and_unserializable_requests_never_reach_network(self):
        for state in ({"text": "x" * 24_000}, {"data": {1, 2}}, {"data": math.nan}, {"data": "\ud800"}, []):
            with self.subTest(state_type=type(state)), patch("jev_ios.baseline.http.client.HTTPSConnection") as connection:
                model = ChatCompletionModel(MODEL, api_key="fixture-key")
                with self.assertRaises(ModelError):
                    self.decide(model, state)
                connection.assert_not_called()
                self.assertEqual(model.calls, 0)

    def test_http_error_has_no_retry_and_no_body_read(self):
        connection = Mock()
        connection.getresponse.return_value.status = 429
        connection.getresponse.return_value.read1.return_value = b"private provider detail"
        with patch("jev_ios.baseline.http.client.HTTPSConnection", return_value=connection):
            model = ChatCompletionModel(MODEL, api_key="private-fixture-key")
            with self.assertRaisesRegex(ModelError, "HTTP 429") as error:
                self.decide(model)
            self.assertNotIn("private", str(error.exception))
            self.assertEqual(model.calls, 1)
            connection.request.assert_called_once()
            connection.getresponse.return_value.read1.assert_not_called()
            connection.close.assert_called_once()

    def test_connection_errors_are_sanitized_and_consume_budget(self):
        for failure in (OSError("private credential detail"), http.client.BadStatusLine("private response")):
            connection = Mock()
            connection.request.side_effect = failure
            with self.subTest(failure=type(failure)), patch("jev_ios.baseline.http.client.HTTPSConnection", return_value=connection):
                model = ChatCompletionModel(MODEL, api_key="private-fixture-key")
                with self.assertRaisesRegex(ModelError, "connection failed or timed out") as error:
                    self.decide(model)
                self.assertNotIn("private", str(error.exception))
                self.assertEqual(model.calls, 1)
                connection.close.assert_called_once()

    def test_response_byte_limit_and_invalid_outer_json(self):
        for content in (b"x" * 256_001, b"private invalid json", b'{"model":"wrong","model":"openai/gpt-5.4-nano"}'):
            connection = Mock()
            connection.getresponse.return_value.status = 200
            connection.getresponse.return_value.read1 = io.BytesIO(content).read1
            with self.subTest(size=len(content)), patch("jev_ios.baseline.http.client.HTTPSConnection", return_value=connection):
                with ChatCompletionModel(MODEL, api_key="fixture-key") as model:
                    with self.assertRaises(ModelError) as error:
                        self.decide(model)
                    self.assertNotIn("private", str(error.exception))
                    self.assertEqual(connection.request.call_count, 1)

    def test_slow_connect_returns_by_deadline_without_late_request(self):
        release = threading.Event()
        closed = threading.Event()
        connection = Mock(sock=None)
        def connect():
            release.wait(1)
            connection.sock = Mock()
        def close():
            if connection.sock is not None:
                closed.set()
        connection.connect.side_effect = connect
        connection.close.side_effect = close
        try:
            with patch("jev_ios.baseline.http.client.HTTPSConnection", return_value=connection):
                model = ChatCompletionModel(MODEL, ModelOptions(timeout_seconds=0.05), api_key="fixture-key")
                started = time.monotonic()
                with self.assertRaisesRegex(ModelError, "connection failed or timed out"):
                    self.decide(model)
                self.assertLess(time.monotonic() - started, 0.25)
                self.assertEqual(model.calls, 1)
                connection.request.assert_not_called()
        finally:
            release.set()
        self.assertTrue(closed.wait(0.5))
        connection.request.assert_not_called()

    def test_trickling_headers_and_body_share_one_wall_deadline(self):
        payload = json.dumps(completion()).encode()
        for phase in ("headers", "body", "fast-close"):
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
                            for offset in range(0, len(payload), 20):
                                self.wfile.write(payload[offset:offset + 20])
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
                with self.subTest(phase=phase), patch("jev_ios.baseline.http.client.HTTPSConnection", side_effect=factory):
                    model = ChatCompletionModel(MODEL, ModelOptions(timeout_seconds=0.12), api_key="fixture-key")
                    started = time.monotonic()
                    if phase == "fast-close":
                        self.assertEqual(self.decide(model)["operation"], "TAP")
                        model.close()
                    else:
                        with self.assertRaisesRegex(ModelError, "connection failed or timed out"):
                            self.decide(model)
                    self.assertLess(time.monotonic() - started, 0.4)
                    self.assertEqual(requests, ["/v1/chat/completions"])
                    self.assertEqual(model.calls, 1)
                    self.assertIsNone(model._connection)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
