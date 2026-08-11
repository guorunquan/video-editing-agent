import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import _pending, _resolve_source, _srt_timestamp, _watermark_region, render_edit_plan, safe_output_stem, trim_keep
from video_analysis import _extract_json, _prepare_ascii_upload, validate_analysis
from tools import _replace_subtitle_pairs
from fastapi import HTTPException
from agent import VideoAgent
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

    def test_analysis_plans_are_normalized_and_get_stable_ids(self):
        raw = {
            "summary": "demo",
            "recommendations": [
                {
                    "strategy": "retention_short",
                    "title": "short",
                    "segments": [{"start_sec": 0, "end_sec": 2, "reason": "opening"}],
                    "estimated_duration_sec": 999,
                },
                {
                    "strategy": "information_complete",
                    "title": "complete",
                    "segments": [{"start_sec": 2, "end_sec": 5, "reason": "key point"}],
                },
            ],
        }
        result = validate_analysis(raw, 10, "video-key")
        self.assertEqual(len(result["recommendations"]), 2)
        self.assertTrue(result["recommendations"][0]["id"].startswith("plan-"))
        self.assertEqual(result["recommendations"][0]["estimated_duration_sec"], 2.0)

    def test_analysis_rejects_overlapping_or_out_of_range_segments(self):
        raw = {
            "recommendations": [
                {
                    "strategy": "retention_short",
                    "segments": [
                        {"start_sec": 0, "end_sec": 3, "reason": "a"},
                        {"start_sec": 2, "end_sec": 4, "reason": "b"},
                    ],
                },
                {
                    "strategy": "information_complete",
                    "segments": [{"start_sec": 9, "end_sec": 11, "reason": "outside"}],
                },
            ]
        }
        result = validate_analysis(raw, 10, "video-key")
        self.assertEqual(result["recommendations"], [])
        self.assertTrue(result["limitations"])

    @patch("tools._video_meta", return_value={"duration_sec": 10, "has_audio": True})
    @patch("tools._resolve_source", return_value=Path("source.mp4"))
    def test_edit_plan_requires_confirmation_before_render(self, _source, _meta):
        result = render_edit_plan(
            segments=[{"start_sec": 0, "end_sec": 3, "reason": "opening"}],
            confirmed=False,
        )
        marker = result.split("\n", 1)[0]
        payload = json.loads(marker.removeprefix("__VIDEO_AGENT_PENDING__"))
        self.assertEqual(payload["tool_name"], "render_edit_plan")
        self.assertEqual(payload["plan"]["estimated_duration_sec"], 3.0)

    @patch("agent.render_edit_plan")
    def test_selected_plan_uses_deterministic_pending_then_confirm_flow(self, render):
        render.side_effect = [
            '__VIDEO_AGENT_PENDING__{"needs_confirm": true}\n【待确认】草案',
            '{"status": "ok", "output": "output/plan.mp4"}',
        ]
        subject = VideoAgent.__new__(VideoAgent)
        subject.history = []
        subject.last_needs_confirm = False
        subject.last_confirmation = None
        subject.last_analysis_for_response = None
        subject.last_analysis_source = "source.mp4"
        subject.last_analysis = {
            "recommendations": [
                {"id": "plan-1", "title": "short", "segments": [{"start_sec": 0, "end_sec": 2}]}
            ]
        }
        subject.pending_selected_plan = None

        pending = subject.chat("采用方案 1")
        self.assertIn("待确认", pending)
        self.assertTrue(subject.last_needs_confirm)
        self.assertTrue(subject.pending_selected_plan)
        done = subject.chat("确认")
        self.assertIn('"status": "ok"', done)
        self.assertEqual(render.call_args_list[0].kwargs["confirmed"], False)
        self.assertEqual(render.call_args_list[1].kwargs["confirmed"], True)

    def test_non_ascii_video_path_uses_temporary_ascii_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "中文视频.mp4"
            source.write_bytes(b"test")
            staged, cleanup = _prepare_ascii_upload(source)
            try:
                self.assertNotEqual(staged, source)
                self.assertTrue(staged.exists())
                staged.as_posix().encode("ascii")
            finally:
                if cleanup:
                    cleanup.unlink(missing_ok=True)

    def test_subtitle_replacement_merges_split_phrase(self):
        blocks = [
            "1\n00:00:01,000 --> 00:00:02,000\n怎么做回甲乙",
            "2\n00:00:02,000 --> 00:00:03,000\n丙丁",
        ]
        rewritten, changed = _replace_subtitle_pairs(
            blocks, [("怎么做回甲乙丙丁", "完成")]
        )
        self.assertEqual(changed, 1)
        self.assertEqual(len(rewritten), 1)
        self.assertIn("完成", rewritten[0])

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
