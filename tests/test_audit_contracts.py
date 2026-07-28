from __future__ import annotations

import importlib.util
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class AuditContractsTest(unittest.TestCase):
    def test_terminology_auditor_detects_and_ignores_history(self) -> None:
        spec = importlib.util.spec_from_file_location("audit_terminology", REPO / "scripts" / "audit_terminology.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docs").mkdir()
            (root / "legacy").mkdir()
            (root / "docs" / "bad.md").write_text("SeqGAN Master\n", encoding="utf-8")
            (root / "legacy" / "old.md").write_text("SeqGAN Master\n", encoding="utf-8")
            findings = module.audit(root, ["docs", "legacy"])
            self.assertEqual(1, len(findings))
            self.assertEqual("docs/bad.md", findings[0].path)

    def test_waf_aliases_are_explicit_in_source(self) -> None:
        source = (REPO / "scripts" / "summarize_waf_results.py").read_text(encoding="utf-8")
        self.assertIn('"waf_not_blocked_rate"', source)
        self.assertIn('"bypass_rate"', source)
        self.assertIn("Historical aliases", source)

    def test_waf_rates_exclude_network_errors(self) -> None:
        spec = importlib.util.spec_from_file_location("summarize_waf_results", REPO / "scripts" / "summarize_waf_results.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        aggregate = module.Aggregate()
        aggregate.add(blocked=True, network_error=False, latency_ms=1.0)
        aggregate.add(blocked=False, network_error=False, latency_ms=1.0)
        aggregate.add(blocked=False, network_error=True, latency_ms=1.0)
        metrics = aggregate.metrics()
        self.assertEqual(2, metrics["eligible_requests"])
        self.assertEqual(0.5, metrics["blocked_rate"])
        self.assertEqual(0.5, metrics["waf_not_blocked_rate"])

    def test_index_summary_has_no_missing_required_artifacts(self) -> None:
        summary_path = REPO / "final_result_info" / "_index" / "summary.json"
        if not summary_path.exists():
            self.skipTest("Sparse checkout does not include the result index")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(0, summary.get("required_artifact_missing_count"))
        self.assertEqual(0, summary.get("campaign_aware_run_key_duplicates"))

    def test_campaign_aware_index_contract(self) -> None:
        spec = importlib.util.spec_from_file_location("audit_provenance", REPO / "scripts" / "audit_provenance.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        result = module.audit(
            REPO / "final_result_info" / "_index" / "run_index.csv",
            REPO / "final_result_info" / "_index" / "summary.json",
        )
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["index_rows"], result["unique_run_keys"])
        self.assertEqual(489, result["thesis_traceability_rows"])
        self.assertEqual(21, result["thesis_table_rows"])

    def test_quality_metric_denominator_excludes_empty_payloads(self) -> None:
        source = (REPO / "common" / "quality_metrics.py").read_text(encoding="utf-8")
        self.assertIn('str(payload) != ""', source)
        self.assertIn('"n_generated": count', source)

    def test_thesis_source_and_selection_manifests(self) -> None:
        source = json.loads((REPO / "final_result_info" / "_index" / "thesis_source_snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(42, source["thesis"]["table_count"])
        self.assertEqual(44, source["presentation"]["slide_count"])
        with (REPO / "final_result_info" / "_provenance" / "decision_artifacts" / "phase3_retained_combinations_thesis.csv").open(encoding="utf-8", newline="") as handle:
            selections = list(csv.DictReader(handle))
        self.assertEqual(11, len(selections))
        self.assertEqual(11, len({(row["family"], row["scenario"], row["variant"]) for row in selections}))

    def test_full_waf_correlation_reproduces_thesis(self) -> None:
        summary = json.loads((REPO / "waf_evaluation" / "waf_evaluation" / "campaign" / "full" / "correlation_summary_canonical.json").read_text(encoding="utf-8"))
        self.assertEqual(489, summary["run_count"])
        self.assertEqual(825899, summary["eligible_request_count"])
        self.assertEqual(585661, summary["blocked_request_count"])
        self.assertEqual(240238, summary["not_blocked_request_count"])
        self.assertEqual(1501, summary["not_sent_too_long_count"])
        expected = {
            "garbage_rate": 0.879048,
            "sql_structure_rate": -0.879048,
            "family_motif_coverage": -0.626259,
            "family_motif_hit_rate": -0.901313,
        }
        for field, value in expected.items():
            self.assertAlmostEqual(value, summary["correlations_with_waf_not_blocked_rate"][field], places=6)
        tables = json.loads((REPO / "waf_evaluation" / "waf_evaluation" / "campaign" / "full" / "thesis_waf_tables_canonical.json").read_text(encoding="utf-8"))
        self.assertEqual(825899, tables["table_3_19"]["eligible_request_count"])
        methods = {row["method_id"]: row for row in tables["table_3_20"]}
        self.assertAlmostEqual(0.9327, methods["seqgan_master"]["waf_not_blocked_rate"], places=4)
        self.assertAlmostEqual(0.4009, methods["seqgan_improved"]["waf_not_blocked_rate"], places=4)

    def test_thesis_unique_columns_are_explicitly_normalized(self) -> None:
        with (REPO / "final_result_info" / "_index" / "thesis_table_manifest.csv").open(encoding="utf-8", newline="") as handle:
            rows = {row["thesis_table_id"]: row for row in csv.DictReader(handle)}
        for table_id in ("Bảng 3.15", "Bảng 3.16", "Bảng 3.17", "Bảng 3.21"):
            self.assertIn("normalized_unique_rate", rows[table_id]["canonical_fields"])


if __name__ == "__main__":
    unittest.main()
