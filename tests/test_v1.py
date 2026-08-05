import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import _pending, _resolve_source, _srt_timestamp, _watermark_region, safe_output_stem, trim_keep
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

    def test_srt_timestamp_format(self):
        self.assertEqual(_srt_timestamp(65.125), "00:01:05,125")

    def test_watermark_region_uses_bottom_right(self):
        region = _watermark_region(
            {"resolution": "1920x1080"}, "bottom_right", None, None, None, None
        )
        self.assertIsNotNone(region)
        x, y, width, height = region
        self.assertGreater(x, 0)
        self.assertGreater(y, 0)
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)

    @patch("tools._list_output_files")
    @patch("tools._get_working_video")
    def test_selected_working_video_beats_latest_output(self, get_working, list_outputs):
        working = Path("selected.mp4")
        latest = Path("latest.mp4")
        get_working.return_value = working
        list_outputs.return_value = [latest]
        self.assertEqual(_resolve_source(prefer_latest_output=True), working)


if __name__ == "__main__":
    unittest.main()
