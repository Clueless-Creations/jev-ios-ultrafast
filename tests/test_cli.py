import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jev_ios.cli import main, parser, scenario_from_args


class CliTests(unittest.TestCase):
    def args(self, *extra):
        return parser().parse_args(['run', '--udid', 'fixture', '--bundle-id', 'example.app', *extra])

    def test_scenario_preserves_defaults_and_supports_explicit_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scenario.json'
            path.write_text(json.dumps({'schema':'jev-ios/scenario/v1', 'name':'test', 'goal':'Open settings',
                'expect_labels':['Settings'], 'max_steps':7, 'allow_scroll':True}))
            scenario = scenario_from_args(self.args('--scenario', str(path)))
            self.assertEqual(scenario.max_steps, 7)
            self.assertTrue(scenario.allow_scroll)
            override = scenario_from_args(self.args('--scenario', str(path), '--no-allow-scroll', '--max-steps', '3'))
            self.assertFalse(override.allow_scroll)
            self.assertEqual(override.max_steps, 3)

    def test_conflicting_or_incomplete_goal_rejected(self):
        for extra in [[], ['--goal', 'Open settings'], ['--expect-label', 'Settings'],
                      ['--scenario', 'unused.json', '--goal', 'Open settings']]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                scenario_from_args(self.args(*extra))

    def test_text_values_and_confidence_validated_before_device_use(self):
        for extra in [['--text','invalid'], ['--text','name='], ['--min-probability','nan'],
                      ['--min-probability','1.1']]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                scenario_from_args(self.args('--goal','Open settings','--expect-label','Settings', *extra))

    def test_existing_or_duplicate_artifacts_rejected_before_device_use(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.jsonl'
            path.write_text('preserve')
            for extra in [['--trace',str(path)], ['--trace',directory+'/new', '--report',directory+'/new'],
                          ['--record-video',directory+'/wrong.mov']]:
                with self.subTest(extra=extra), patch('jev_ios.cli.AxeDevice') as device, contextlib.redirect_stdout(io.StringIO()):
                    status = main(['run','--udid','fixture','--bundle-id','example.app',
                        '--goal','Open settings','--expect-label','Settings', *extra])
                    self.assertEqual(status, 1)
                    device.assert_not_called()
            self.assertEqual(path.read_text(), 'preserve')

    def test_provider_errors_do_not_expose_response(self):
        from jev_ios.cli import temporary_vercel_token
        with patch('jev_ios.cli.subprocess.run') as command:
            command.return_value.returncode = 1
            command.return_value.stdout = 'private-test-token'
            command.return_value.stderr = 'private-test-token'
            with self.assertRaises(ValueError) as error:
                temporary_vercel_token('example-project')
            self.assertNotIn('private-test-token', str(error.exception))
