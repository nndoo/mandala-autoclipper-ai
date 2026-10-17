import unittest

from backend.editing_dispatch import _safe_exception_frames


class SafeExceptionFramesTests(unittest.TestCase):
    def test_returns_frame_locations_without_exception_message(self):
        secret_like_message = "provider error with bearer-FAKE-SECRET-DO-NOT-LOG"
        try:
            raise RuntimeError(secret_like_message)
        except RuntimeError as exc:
            result = _safe_exception_frames(exc)

        self.assertIn("test_editing_dispatch_diagnostics.py", result)
        self.assertIn("test_returns_frame_locations_without_exception_message", result)
        self.assertNotIn(secret_like_message, result)
        self.assertNotIn("FAKE-SECRET", result)


if __name__ == "__main__":
    unittest.main()
