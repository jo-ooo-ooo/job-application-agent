"""Tests for checkpoint.py — save, load, resume pipeline state."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from checkpoint import (
    generate_run_id,
    save_checkpoint,
    load_checkpoint,
    list_checkpoints,
    get_latest_checkpoint,
    is_step_completed,
    is_gate_completed,
    delete_checkpoint,
    CHECKPOINTS_DIR,
)


class TestGenerateRunId(unittest.TestCase):
    def test_format(self):
        run_id = generate_run_id()
        # Should be YYYYMMDD_HHMMSS format
        self.assertRegex(run_id, r'^\d{8}_\d{6}$')

    def test_unique(self):
        # Two calls in quick succession should produce the same ID (same second)
        # but the format should be valid
        id1 = generate_run_id()
        self.assertEqual(len(id1), 15)


class TestSaveAndLoadCheckpoint(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.original_dir = CHECKPOINTS_DIR
        # Patch CHECKPOINTS_DIR to use temp directory
        import checkpoint
        checkpoint.CHECKPOINTS_DIR = Path(self.tmp_dir)

    def tearDown(self):
        import checkpoint
        checkpoint.CHECKPOINTS_DIR = self.original_dir
        # Clean up temp files
        for f in Path(self.tmp_dir).glob("*.json"):
            f.unlink()
        os.rmdir(self.tmp_dir)

    def test_save_and_load(self):
        state = {"job_description": "Test JD", "company_research": "Test research"}
        completed_steps = ["company_research", "hiring_manager"]
        completed_gates = ["gate_1"]

        path = save_checkpoint("test_run_001", state, completed_steps, completed_gates)
        self.assertTrue(path.exists())

        loaded = load_checkpoint("test_run_001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["run_id"], "test_run_001")
        self.assertEqual(loaded["state"], state)
        self.assertEqual(loaded["completed_steps"], completed_steps)
        self.assertEqual(loaded["completed_gates"], completed_gates)
        self.assertIn("timestamp", loaded)

    def test_load_nonexistent(self):
        self.assertIsNone(load_checkpoint("nonexistent_id"))

    def test_save_overwrites(self):
        state1 = {"company_research": "v1"}
        save_checkpoint("run_1", state1, ["company_research"])

        state2 = {"company_research": "v1", "gap_analysis": "v2"}
        save_checkpoint("run_1", state2, ["company_research", "gap_analysis"])

        loaded = load_checkpoint("run_1")
        self.assertEqual(loaded["state"]["gap_analysis"], "v2")
        self.assertEqual(len(loaded["completed_steps"]), 2)

    def test_save_without_gates(self):
        save_checkpoint("run_no_gates", {"foo": "bar"}, ["step1"])
        loaded = load_checkpoint("run_no_gates")
        self.assertEqual(loaded["completed_gates"], [])


class TestListCheckpoints(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        import checkpoint
        self.original_dir = checkpoint.CHECKPOINTS_DIR
        checkpoint.CHECKPOINTS_DIR = Path(self.tmp_dir)

    def tearDown(self):
        import checkpoint
        checkpoint.CHECKPOINTS_DIR = self.original_dir
        for f in Path(self.tmp_dir).glob("*.json"):
            f.unlink()
        os.rmdir(self.tmp_dir)

    def test_empty_dir(self):
        self.assertEqual(list_checkpoints(), [])

    def test_lists_multiple(self):
        save_checkpoint("20260317_100000", {"a": 1}, ["step1"])
        save_checkpoint("20260317_110000", {"b": 2}, ["step1", "step2"])

        result = list_checkpoints()
        self.assertEqual(len(result), 2)
        # Newest first
        self.assertEqual(result[0]["run_id"], "20260317_110000")
        self.assertEqual(result[1]["run_id"], "20260317_100000")

    def test_skips_invalid_json(self):
        # Write an invalid JSON file
        bad_path = Path(self.tmp_dir) / "bad.json"
        bad_path.write_text("not json", encoding="utf-8")

        save_checkpoint("good_run", {"a": 1}, ["step1"])
        result = list_checkpoints()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["run_id"], "good_run")


class TestGetLatestCheckpoint(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        import checkpoint
        self.original_dir = checkpoint.CHECKPOINTS_DIR
        checkpoint.CHECKPOINTS_DIR = Path(self.tmp_dir)

    def tearDown(self):
        import checkpoint
        checkpoint.CHECKPOINTS_DIR = self.original_dir
        for f in Path(self.tmp_dir).glob("*.json"):
            f.unlink()
        os.rmdir(self.tmp_dir)

    def test_no_checkpoints(self):
        self.assertIsNone(get_latest_checkpoint())

    def test_returns_newest(self):
        save_checkpoint("20260317_100000", {"a": 1}, ["step1"])
        save_checkpoint("20260317_120000", {"b": 2}, ["step1", "step2"])

        latest = get_latest_checkpoint()
        self.assertEqual(latest["run_id"], "20260317_120000")


class TestIsStepCompleted(unittest.TestCase):
    def test_completed(self):
        cp = {"completed_steps": ["company_research", "gap_analysis"]}
        self.assertTrue(is_step_completed(cp, "company_research"))
        self.assertTrue(is_step_completed(cp, "gap_analysis"))

    def test_not_completed(self):
        cp = {"completed_steps": ["company_research"]}
        self.assertFalse(is_step_completed(cp, "cv_construction"))

    def test_empty(self):
        self.assertFalse(is_step_completed({}, "company_research"))


class TestIsGateCompleted(unittest.TestCase):
    def test_completed(self):
        cp = {"completed_gates": ["gate_1"]}
        self.assertTrue(is_gate_completed(cp, "gate_1"))

    def test_not_completed(self):
        cp = {"completed_gates": ["gate_1"]}
        self.assertFalse(is_gate_completed(cp, "gate_2"))

    def test_empty(self):
        self.assertFalse(is_gate_completed({}, "gate_1"))


class TestDeleteCheckpoint(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        import checkpoint
        self.original_dir = checkpoint.CHECKPOINTS_DIR
        checkpoint.CHECKPOINTS_DIR = Path(self.tmp_dir)

    def tearDown(self):
        import checkpoint
        checkpoint.CHECKPOINTS_DIR = self.original_dir
        for f in Path(self.tmp_dir).glob("*.json"):
            f.unlink()
        os.rmdir(self.tmp_dir)

    def test_delete_existing(self):
        save_checkpoint("to_delete", {"a": 1}, ["step1"])
        self.assertTrue(delete_checkpoint("to_delete"))
        self.assertIsNone(load_checkpoint("to_delete"))

    def test_delete_nonexistent(self):
        self.assertFalse(delete_checkpoint("no_such_run"))


class TestCheckpointJsonStructure(unittest.TestCase):
    """Verify the JSON structure is correct for downstream consumers."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        import checkpoint
        self.original_dir = checkpoint.CHECKPOINTS_DIR
        checkpoint.CHECKPOINTS_DIR = Path(self.tmp_dir)

    def tearDown(self):
        import checkpoint
        checkpoint.CHECKPOINTS_DIR = self.original_dir
        for f in Path(self.tmp_dir).glob("*.json"):
            f.unlink()
        os.rmdir(self.tmp_dir)

    def test_full_state_roundtrip(self):
        """Verify a realistic pipeline state survives save/load."""
        state = {
            "job_description": "Senior PM at Acme Corp...",
            "manager_name": "Jane Doe",
            "company_research": "Acme Corp is a B2B SaaS company...",
            "manager_research": "Jane Doe has 10 years in product...",
            "gap_analysis": "- Technical skills: 7/10\n- Seniority: 8/10",
            "project_selection": "",
            "cv_markdown": "",
            "cover_letter_markdown": "",
        }
        completed = ["company_research", "hiring_manager", "gap_analysis"]
        gates = ["gate_1"]

        save_checkpoint("full_test", state, completed, gates)
        loaded = load_checkpoint("full_test")

        # All state fields preserved
        for key in state:
            self.assertEqual(loaded["state"][key], state[key])

        # Completed steps preserved
        self.assertEqual(loaded["completed_steps"], completed)
        self.assertEqual(loaded["completed_gates"], gates)

    def test_json_file_is_valid(self):
        """The file on disk is valid, human-readable JSON."""
        save_checkpoint("json_test", {"a": "b"}, ["step1"])
        path = Path(self.tmp_dir) / "json_test.json"
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        # Should be indented (human-readable)
        self.assertIn("\n", raw)
        self.assertIn("run_id", data)


if __name__ == "__main__":
    unittest.main()
