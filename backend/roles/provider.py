"""Existing Stage 5 transports. Live mode is an explicit service opt-in."""

import os
from pathlib import Path


class LiveProvider:
    def __init__(self, *, enabled=False):
        self.enabled = enabled

    def ready(self):
        return self.enabled

    @staticmethod
    def _require():
        if os.getenv('MANDALA_EDITING_LIVE_ROLES_ENABLED') != '1':
            raise RuntimeError('Live role transport disabled')

    def analyst(self, video):
        self._require()
        import review_video_quality_v01 as reviewer
        import run_adaptive_director_v03 as director

        runtime = director.RUNTIME
        executable = runtime / 'bin/openclaw'
        node = runtime / 'tools/node-v24.21.0/bin'
        node_executable = node / 'node'

        if (
            not executable.is_file()
            or not node.is_dir()
            or not node_executable.is_file()
        ):
            raise RuntimeError('Isolated OpenClaw runtime unavailable')

        env = os.environ.copy()
        env['PATH'] = f'{node}:{runtime / "bin"}:{env.get("PATH", "")}'
        env['NODE_OPTIONS'] = '--max-old-space-size=256'
        return reviewer.capture_inference([
            str(executable), 'infer', 'video', 'describe', '--agent',
            'mandala-video-analyst', '--model', reviewer.PROVIDER + '/' + reviewer.MODEL,
            '--file', str(video), '--json'], env=env, timeout=180,
            max_bytes=131072)

    def director(self, prompt, images):
        self._require()
        from run_adaptive_director_v03 import live_response
        return live_response(prompt, approved=True, image_paths=images)

    def asr(self, config, wav, temporary):
        self._require()
        from generate_remote_speech_evidence_v01 import remote_call
        return remote_call(config, wav, temporary)

    def reviewer(self, request, path):
        self._require()
        from review_video_quality_v01 import invoke
        return invoke(request, path, approved=True)


class TestOnlyReplayProvider:
    """Explicitly injected synthetic replies; never selected from environment."""

    test_only = True

    def __init__(self, replies):
        self.replies = {name: list(values) for name, values in replies.items()}

    def ready(self):
        return True

    def _take(self, name):
        queue = self.replies.get(name)
        if not queue:
            raise RuntimeError('TEST_ONLY replay response unavailable')
        value = queue.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def analyst(self, video):
        return self._take('analyst')

    def director(self, prompt, images):
        return self._take('director')

    def asr(self, config, wav, temporary):
        return self._take('asr')

    def reviewer(self, request, path):
        return self._take('reviewer')