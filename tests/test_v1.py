import json
import unittest

from tools import _pending, safe_output_stem, trim_keep
from video_analysis import _extract_json
from fastapi import HTTPException
from web_app import _preview_file


class V1SafetyTests(unittest.TestCase):
    def test_filename_keeps_decimal_point(self):
        self.assertEqual(safe_output_stem("1.5倍速视频.mp4"), "1.5倍速视频")

    def test_filename_rejects_path_separators(self):
        stem = safe_output_stem("..\\secret/output.mp4")
        self.assertNotIn("/", stem)
        self.assertNotIn("\\", stem)

    def test_pending_contains_machine_readable_confirmation(self):
        result = _pending(
            "切片计划",
            "保留 0 到 3 秒",
            {"action": "trim_keep", "start_sec": 0, "end_sec": 3},
            "trim_keep",
        )
        marker = result.split("\n", 1)[0]
        payload = json.loads(marker.removeprefix("__VIDEO_AGENT_PENDING__"))
        self.assertTrue(payload["needs_confirm"])
        self.assertEqual(payload["tool_name"], "trim_keep")

    def test_invalid_trim_does_not_write(self):
        result = trim_keep(-1, 3)
        self.assertIn("错误", result)

    def test_analysis_json_accepts_code_fence(self):
        result = _extract_json('```json\n{"summary":"demo","recommendations":[]}\n```')
        self.assertEqual(result["summary"], "demo")

    def test_preview_path_is_restricted_to_preview_directory(self):
        with self.assertRaises(HTTPException):
            _preview_file("..\\secret.mp4")


if __name__ == "__main__":
    unittest.main()
