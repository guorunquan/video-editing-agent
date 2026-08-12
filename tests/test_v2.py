import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from editor_v2 import (
    _automatic_music,
    _beat_snapped_segments,
    _build_render_command,
    _expand_slow_motion_segments,
    confirm_draft,
    create_draft,
)
from agent import VideoAgent
from video_analysis import _prompt, analyze_video


class V2DraftTests(unittest.TestCase):
    @patch("editor_v2._safe_music", side_effect=lambda name: Path(name))
    @patch("editor_v2.list_music")
    def test_high_energy_plan_automatically_picks_matching_music(self, library, _safe):
        library.return_value = [
            {"name": "calm.wav", "bpm": 92, "builtin": False},
            {"name": "energy-edm.wav", "bpm": 150, "builtin": False},
        ]
        selected = _automatic_music({"strategy": "retention_short", "package": {"music_mood": "高燃电子"}})
        self.assertEqual(selected, Path("energy-edm.wav"))

    @patch("editor_v2._run_text")
    def test_preview_keeps_source_resolution_and_crf20(self, run):
        run.return_value.stderr = "Video: h264, yuv420p, 1920x1080, 30 fps Audio: aac"
        draft = {
            "source": "source.mp4",
            "segments": [{"start_sec": 0, "end_sec": 2}],
            "effects": [],
            "transition": {},
            "music": {"path": None},
        }
        command, _ = _build_render_command(draft, Path("preview.mp4"), preview=True)
        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn("scale=1920:1080", filter_graph)
        self.assertEqual(command[command.index("-crf") + 1], "20")
        self.assertEqual(command[command.index("-preset") + 1], "veryfast")

    def test_plan_preview_intent_supports_natural_chinese_phrases(self):
        cases = {
            "看看方案三": 3,
            "预览方案 2": 2,
            "采用第一个方案": 1,
            "方案三看看": 3,
            "方案一配上高燃音乐": 1,
            "给方案 2 加配乐": 2,
            "方案一": 1,
            "方案 3！": 3,
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(VideoAgent._selected_plan_number(phrase), expected)

    def test_music_request_is_handled_without_gemini(self):
        self.assertTrue(VideoAgent._looks_like_music_request("能来一段高燃配乐吗"))
        self.assertTrue(VideoAgent._looks_like_music_request("配上高燃音乐"))
        self.assertTrue(VideoAgent._looks_like_music_request("加上动感背景乐"))
        self.assertFalse(VideoAgent._looks_like_music_request("自动加字幕"))

    @patch("agent.render_draft")
    @patch("agent.create_draft")
    @patch("agent._video_meta", return_value={"duration_sec": 18.0})
    @patch("agent._resolve_source", return_value=Path("source.mp4"))
    def test_music_request_without_draft_creates_whole_video_mix_preview(self, _source, _meta, create, render):
        create.return_value = {"id": "draft-12345678", "plan_id": "whole-video-soundtrack"}
        render.return_value = {
            "path": "output/plan_previews/whole.mp4",
            "draft": {"music": {"name": "energy.wav", "volume": 0.38}},
        }
        subject = VideoAgent.__new__(VideoAgent)
        subject.history = []
        subject.last_needs_confirm = False
        subject.last_confirmation = None
        subject.last_analysis_for_response = None
        subject.last_analysis = None
        subject.last_analysis_source = None
        subject.last_preview_path = None
        subject.last_output_path = None
        subject.pending_selected_plan = None
        subject.active_draft_id = None
        result = subject.chat("给整个原视频直接配一段高燃音乐")
        self.assertIn("保留整段原视频的画面和原声", result)
        plan = create.call_args.args[1]
        self.assertEqual(plan["segments"], [{"start_sec": 0.0, "end_sec": 18.0, "reason": "保留整段画面与原声，只混入背景配乐"}])
        self.assertEqual(plan["package"]["music_mood"], "高燃电子")
        self.assertEqual(subject.last_preview_path, "output/plan_previews/whole.mp4")
        render.assert_called_once_with("draft-12345678", preview=True)

    def test_unsatisfied_request_returns_to_source(self):
        subject = VideoAgent.__new__(VideoAgent)
        subject.history = []
        subject.last_needs_confirm = False
        subject.last_confirmation = None
        subject.last_analysis_for_response = None
        subject.last_preview_path = None
        subject.last_output_path = None
        subject.pending_selected_plan = {"draft_id": "draft-12345678", "plan_id": "plan-1"}
        subject.active_draft_id = "draft-12345678"
        result = subject.chat("不满意，返回原视频")
        self.assertIn("已取消", result)
        self.assertIsNone(subject.pending_selected_plan)
        self.assertIsNone(subject.active_draft_id)

    @patch("agent.render_draft")
    @patch("agent.update_draft_music")
    def test_active_draft_music_request_rerenders_preview(self, update_music, render):
        update_music.return_value = {"id": "draft-12345678", "plan_id": "plan-1"}
        render.return_value = {
            "path": "output/plan_previews/music.mp4",
            "draft": {"music": {"name": "energy.wav"}},
        }
        subject = VideoAgent.__new__(VideoAgent)
        subject.history = []
        subject.last_needs_confirm = False
        subject.last_confirmation = None
        subject.last_analysis_for_response = None
        subject.last_preview_path = None
        subject.last_output_path = None
        subject.pending_selected_plan = {"draft_id": "draft-12345678", "plan_id": "plan-1"}
        subject.active_draft_id = "draft-12345678"
        result = subject.chat("配上高燃音乐")
        self.assertIn("energy.wav", result)
        self.assertEqual(subject.last_preview_path, "output/plan_previews/music.mp4")
        update_music.assert_called_once_with("draft-12345678", mood="高燃电子")
        render.assert_called_once_with("draft-12345678", preview=True)

    def test_legacy_plan_renderer_is_not_exposed_to_gemini(self):
        subject = VideoAgent.__new__(VideoAgent)
        from agent import _build_tools

        names = [declaration.name for tool in _build_tools() for declaration in tool.function_declarations]
        self.assertNotIn("render_edit_plan", names)

    @patch("agent.set_working_video", return_value=Path("output/final.mp4"))
    @patch("agent.confirm_draft", return_value={"path": "output/final.mp4"})
    def test_text_confirmation_exports_previewed_draft(self, confirm, set_working):
        subject = VideoAgent.__new__(VideoAgent)
        subject.history = []
        subject.last_needs_confirm = False
        subject.last_confirmation = None
        subject.last_analysis_for_response = None
        subject.last_preview_path = None
        subject.last_output_path = None
        subject.active_draft_id = "draft-12345678"
        subject.pending_selected_plan = {"draft_id": "draft-12345678", "plan_id": "plan-1"}
        result = subject.chat("确认")
        self.assertIn("已确认并导出", result)
        confirm.assert_called_once_with("draft-12345678")
        set_working.assert_called_once()
        self.assertEqual(subject.last_output_path, "output\\final.mp4")
        self.assertIsNone(subject.active_draft_id)

    def test_full_v2_analysis_prompt_renders_valid_json_example(self):
        prompt = _prompt(
            {"duration_sec": 60, "resolution": "1920x1080"},
            {"status": "ok", "segments": []},
        )
        self.assertIn('"package": {"music": {', prompt)
        self.assertIn('"transition": {"type": "crossfade"', prompt)
        self.assertIn('"effects": [{"type":', prompt)

    def test_analysis_include_data_keeps_tuple_contract_on_missing_file(self):
        message, analysis = analyze_video(object(), "demo", Path("missing-video.mp4"), include_data=True)
        self.assertIn("找不到视频", message)
        self.assertEqual(analysis, {})

    @patch("video_analysis._local_transcript", side_effect=ValueError("real analysis failure"))
    @patch("video_analysis._prepare_ascii_upload", side_effect=lambda video: (video, None))
    def test_analysis_include_data_preserves_real_failure(self, _prepare, _transcript):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "source.mp4"
            video.write_bytes(b"video")
            message, analysis = analyze_video(object(), "demo", video, include_data=True)
        self.assertIn("real analysis failure", message)
        self.assertNotIn("too many values to unpack", message)
        self.assertEqual(analysis, {})

    def test_draft_requires_preview_before_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            source.write_bytes(b"placeholder")
            with patch("editor_v2.DRAFT_DIR", Path(temp_dir) / "drafts"):
                draft = create_draft(source, {"id": "plan-1", "segments": [{"start_sec": 0, "end_sec": 2}]})
                with self.assertRaisesRegex(ValueError, "先生成并观看"):
                    confirm_draft(draft["id"])

    def test_slow_motion_only_splits_requested_highlight(self):
        segments = [{"start_sec": 0, "end_sec": 5, "reason": "play"}]
        effects = [{"type": "slow_motion", "start_sec": 2, "duration_sec": 1, "speed": 0.5}]
        expanded = _expand_slow_motion_segments(segments, effects)
        self.assertEqual([(row["start_sec"], row["end_sec"], row["speed"]) for row in expanded], [
            (0.0, 2.0, 1.0), (2.0, 3.0, 0.5), (3.0, 5.0, 1.0)
        ])

    def test_beat_sync_never_moves_cut_more_than_safety_window(self):
        draft = {
            "segments": [{"start_sec": 0, "end_sec": 2.1}, {"start_sec": 3, "end_sec": 5}],
            "music": {"beat_sync": True, "analysis": {"beat_times": [0, 1, 2, 3]}},
        }
        snapped = _beat_snapped_segments(draft)
        self.assertEqual(snapped[0]["end_sec"], 2.0)
        self.assertEqual(snapped[1]["start_sec"], 3)


if __name__ == "__main__":
    unittest.main()
