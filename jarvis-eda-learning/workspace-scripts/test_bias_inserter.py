"""
test_bias_inserter.py
=====================
Unit tests for gate_bias_network.py and ads_bias_inserter.py (dry-run path).
No ADS installation required — all tests run in plain Python.

Run:
    python workspace-scripts/test_bias_inserter.py
    (or from workspace-scripts/: python test_bias_inserter.py)
"""

import sys
import os
import io
import math
import unittest
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
# Allow running from repo root or from workspace-scripts/
REPO_ROOT    = Path(__file__).resolve().parent.parent
SCRIPTS_DIR  = REPO_ROOT / "workspace-scripts"
BIAS_RULES   = REPO_ROOT / "bias-rules" / "switch_gate_bias.yaml"
PROC_YAML    = REPO_ROOT / "bias-rules" / "process-defaults" / "gaas_phemt.yaml"
PDK_CONFIG   = REPO_ROOT / "pdk-configs" / "WIN_PP1029_core.yaml"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from gate_bias_network import BiasComponents, FETParams, BiasSpecs, calculate_bias

try:
    from gate_bias_network import format_rs, format_cp
    _FORMAT_HELPERS_AVAILABLE = True
except ImportError:
    _FORMAT_HELPERS_AVAILABLE = False
    def format_rs(v): return f"{int(round(v/10)*10)} Ohm"
    def format_cp(v): return f"{v:.4f} pF"

# Load YAML without ADS — use PyYAML directly
try:
    import yaml as _yaml
    def _load_yaml(path):
        with open(path, "r", encoding="utf-8") as f:
            return _yaml.safe_load(f)
except ImportError:
    _yaml = None
    def _load_yaml(path):
        raise unittest.SkipTest("PyYAML not installed — cannot load YAML files")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — calculate_bias: large series FET (ugw=160 total, nof=2)
# ══════════════════════════════════════════════════════════════════════════════

class TestCalculateBiasLargeFET(unittest.TestCase):
    """
    Series FET: Q1a-equivalent, ugw=160 µm total (2×80 µm), nof=2.
    Expected physics (526-line API, PP1029 defaults):
      Cgs = 0.75×160 + 10 = 130 fF
      Zgate at f_high = 1/(2π×18e9×130e-15) = 68.0 Ω
      rs_floor_isolation = 10×68.0 = 680 Ω  (Rule 2)
      rs_min = max(1000, 680) = 1000 Ω  (stability floor dominates, Rule 1)
      rs_max = 1e-9/(2.2×130e-15) = 3497 Ω  (feasible window, Rule 3)
      rs_bias = 1000 Ω
      cp_min = 10/(2π×2e9×1000) = 795.8 fF  (RF bypass floor, Rule 4)
      cp_bypass = 3×795.8 = 2387 fF  (3× margin applied)
      t_sw_actual = 2.2×(1000×130e-15)×1e9 = 0.286 ns ≤ 1.0 ns → t_sw_ok=True
      tau_ctrl = 50×2387e-15 = 119.4 ps; t_ctrl = 0.263 ns ≤ 0.5 ns → t_ctrl_ok=True
    """
    def setUp(self):
        self.fet = FETParams(
            ugw=160, nof=2, ugw_per_finger=80,
            cgs_um=0.75, cgd_um=0.15, cstray=10.0,
        )
        self.specs = BiasSpecs(f_low=2.0, f_high=18.0, t_sw=1.0, r_ctrl=50.0)
        self.result = calculate_bias(self.fet, self.specs)

    def test_rs_bias_meets_stability_floor(self):
        self.assertGreaterEqual(self.result.rs_bias, 1000.0,
                                "rs_bias must be ≥ stability_floor (1000 Ohm)")

    def test_cp_bypass_positive(self):
        self.assertGreater(self.result.cp_bypass, 0.0,
                           "cp_bypass must be a positive fF value")

    def test_rs_ok_true(self):
        self.assertTrue(self.result.rs_ok,
                        "rs_ok must be True when rs_bias is within design window")

    def test_t_sw_ok_true(self):
        self.assertTrue(self.result.t_sw_ok,
                        "t_sw_ok must be True: 2.2×tau_gate ≤ 1.0 ns spec")

    def test_cp_ok_true(self):
        self.assertTrue(self.result.cp_ok,
                        "cp_ok must be True when cp_bypass meets RF bypass floor")

    def test_t_ctrl_ok_true(self):
        self.assertTrue(self.result.t_ctrl_ok,
                        "t_ctrl_ok must be True: ctrl settling time ≤ t_sw/2")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — calculate_bias: small shunt FET (ugw=100 total, nof=2)
# ══════════════════════════════════════════════════════════════════════════════

class TestCalculateBiasSmallFET(unittest.TestCase):
    """
    Shunt FET: Q3a-equivalent, ugw=100 µm total (2×50 µm), nof=2.
    With Rule 2 (RF isolation), smaller Cgs → higher |Zgate| → isolation floor
    dominates the stability floor for this device:
      Cgs = 0.75×100 + 10 = 85 fF
      Zgate at f_high = 1/(2π×18e9×85e-15) = 104 Ω
      rs_floor_isolation = 10×104 = 1040 Ω  (dominates stability floor of 1000 Ω)
      rs_bias = 1040 Ω
    Large FET (ugw=160 total): rs_bias = 1000 Ω (stability floor dominates)
    Smaller FET requires HIGHER Rs than the larger FET in this regime.
    """
    def setUp(self):
        self.fet_small = FETParams(
            ugw=100, nof=2, ugw_per_finger=50,
            cgs_um=0.75, cgd_um=0.15, cstray=10.0,
        )
        self.fet_large = FETParams(
            ugw=160, nof=2, ugw_per_finger=80,
            cgs_um=0.75, cgd_um=0.15, cstray=10.0,
        )
        specs = BiasSpecs(f_low=2.0, f_high=18.0, t_sw=1.0, r_ctrl=50.0)
        self.small = calculate_bias(self.fet_small, specs)
        self.large = calculate_bias(self.fet_large, specs)

    def test_rs_bias_meets_stability_floor(self):
        self.assertGreaterEqual(self.small.rs_bias, 1000.0,
                                "small FET rs_bias must be ≥ stability_floor")

    def test_rs_small_geq_large(self):
        # Smaller Cgs → higher |Zgate| → isolation floor dominates →
        # small FET requires higher Rs than the large FET.
        self.assertGreaterEqual(self.small.rs_bias, self.large.rs_bias,
                                "smaller FET needs equal or higher Rs (isolation rule dominates)")

    def test_cp_bypass_positive(self):
        self.assertGreater(self.small.cp_bypass, 0.0,
                           "cp_bypass must be positive fF")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — format_rs and format_cp
# ══════════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(_FORMAT_HELPERS_AVAILABLE,
                     "format_rs/format_cp not in this gate_bias_network version")
class TestFormatFunctions(unittest.TestCase):
    """
    Verify string formatting helpers produce the expected output strings.
    Note: cp_bypass from calculate_bias is in fF (e.g. 2387 fF = 2.387 pF).
    format_cp accepts a value in pF and formats it — used for display conversion.
    """
    def test_format_rs_exact_floor(self):
        self.assertEqual(format_rs(1000.0), "1000 Ohm")

    def test_format_rs_rounding(self):
        # 1234 rounds to 1230; 1235 rounds to 1240
        self.assertEqual(format_rs(1234.0), "1230 Ohm")
        self.assertEqual(format_rs(1235.0), "1240 Ohm")

    def test_format_cp_four_decimal_places(self):
        # 2.387 pF → "2.3870 pF"
        self.assertEqual(format_cp(2.387), "2.3870 pF")

    def test_format_cp_unit_label(self):
        result = format_cp(0.7958)
        self.assertTrue(result.endswith(" pF"),
                        f"format_cp result must end with ' pF', got: {result!r}")

    def test_format_cp_small_value(self):
        # The physics cp floor for rs=1000, f_low=2GHz is ~0.7958 pF
        cp_F = 1.0 / (2.0 * math.pi * 2e9 * 100.0)
        cp_pF = cp_F * 1e12
        result = format_cp(cp_pF)
        self.assertIn(".", result)
        self.assertTrue(result.endswith(" pF"))


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 — Load switch_gate_bias.yaml and validate structure
# ══════════════════════════════════════════════════════════════════════════════

class TestSwitchGateBiasYAML(unittest.TestCase):
    """Validate switch_gate_bias.yaml has all required fields."""

    def setUp(self):
        self.yaml = _load_yaml(BIAS_RULES)

    def test_bias_type(self):
        self.assertEqual(self.yaml["bias_type"], "switch_gate")

    def test_specs_f_low(self):
        self.assertAlmostEqual(float(self.yaml["specs"]["f_low"]), 2.0)

    def test_specs_f_high(self):
        self.assertAlmostEqual(float(self.yaml["specs"]["f_high"]), 18.0)

    def test_control_series_vg_on(self):
        self.assertAlmostEqual(float(self.yaml["control"]["series_vg_on"]), 0.0)

    def test_control_series_vg_off(self):
        self.assertAlmostEqual(float(self.yaml["control"]["series_vg_off"]), -0.5)

    def test_control_shunt_vg_on(self):
        self.assertAlmostEqual(float(self.yaml["control"]["shunt_vg_on"]), -0.5)

    def test_control_shunt_vg_off(self):
        self.assertAlmostEqual(float(self.yaml["control"]["shunt_vg_off"]), 0.0)

    def test_fet_roles_series_vctrl_on(self):
        self.assertAlmostEqual(
            float(self.yaml["fet_roles"]["series"]["vctrl_on"]), 0.0)

    def test_fet_roles_shunt_vctrl_on(self):
        self.assertAlmostEqual(
            float(self.yaml["fet_roles"]["shunt"]["vctrl_on"]), -0.5)

    def test_subcell_name(self):
        self.assertEqual(self.yaml["subcell"]["name"], "GBIAS_SWITCH_GATE")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5 — Load gaas_phemt.yaml and validate structure
# ══════════════════════════════════════════════════════════════════════════════

class TestGaasPHEMTYAML(unittest.TestCase):
    """Validate gaas_phemt.yaml has required process constants."""

    def setUp(self):
        self.yaml = _load_yaml(PROC_YAML)

    def test_process_type(self):
        self.assertEqual(self.yaml["process_type"], "gaas_phemt")

    def test_cgs_um_in_range(self):
        # Literature range 0.6–0.9 fF/µm; file uses 0.75
        self.assertGreaterEqual(float(self.yaml["cgs_um"]), 0.5)
        self.assertLessEqual(float(self.yaml["cgs_um"]), 1.0)

    def test_cgd_um_present(self):
        self.assertIn("cgd_um", self.yaml)
        self.assertGreater(float(self.yaml["cgd_um"]), 0.0)

    def test_rs_stability_floor(self):
        self.assertGreaterEqual(float(self.yaml["rs_stability_floor"]), 1000.0)

    def test_cstray_present(self):
        self.assertIn("cstray", self.yaml)
        self.assertGreater(float(self.yaml["cstray"]), 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6 — ads_bias_inserter.py dry-run output
# ══════════════════════════════════════════════════════════════════════════════

class TestDryRunOutput(unittest.TestCase):
    """
    Exercise ads_bias_inserter.insert_bias_networks() in dry-run mode.
    Captures stdout and asserts all 4 FETs are mentioned with correct parameters.
    Requires PDK config YAML to exist.
    """

    def _run_dry_run(self):
        """Capture stdout from insert_bias_networks(..., dry_run=True)."""
        import ads_bias_inserter as abi

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            abi.insert_bias_networks(
                workspace_path  = str(REPO_ROOT / "fake_workspace"),
                schematic_name  = "spdt_switch",
                bias_rules_path = str(BIAS_RULES),
                pdk_config_path = str(PDK_CONFIG),
                dry_run         = True,
            )
        finally:
            sys.stdout = old_stdout
        return buf.getvalue()

    def test_all_fets_mentioned(self):
        output = self._run_dry_run()
        for fet_name in ("Q1a", "Q3a", "Q1b", "Q3b"):
            self.assertIn(fet_name, output,
                          f"FET {fet_name} not found in dry-run output")

    def test_parameter_lines_present(self):
        output = self._run_dry_run()
        # Each FET line should contain Rs=, Cp=, Vctrl=
        for label in ("Rs=", "Cp=", "Vctrl="):
            self.assertIn(label, output,
                          f"Expected '{label}' in dry-run output")

    def test_series_vctrl_zero(self):
        output = self._run_dry_run()
        # Series FETs (Q1a, Q1b) should report Vctrl=0.0 V
        # The output line format: [Q1a] role=series  Rs=...  Vctrl=0.0 V
        self.assertIn("Vctrl=0.0 V", output,
                      "Series FET Vctrl should be 0.0 V in dry-run output")

    def test_shunt_vctrl_negative(self):
        output = self._run_dry_run()
        # Shunt FETs (Q3a, Q3b) should report Vctrl=-0.5 V
        self.assertIn("Vctrl=-0.5 V", output,
                      "Shunt FET Vctrl should be -0.5 V in dry-run output")

    def test_dry_run_tag_present(self):
        output = self._run_dry_run()
        self.assertIn("[DRY", output,
                      "Dry-run output should contain [DRY ] tags")

    def test_no_ads_exception(self):
        """Dry-run must complete without raising any exception."""
        try:
            self._run_dry_run()
        except Exception as exc:
            self.fail(f"Dry-run raised an unexpected exception: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
