"""
ATHER (SkyGuard AI) — Evaluation Benchmark Suite.
Mapped against SIH 2026 Rubric Criteria:
1. Detection Accuracy (20%): Precision, Recall, F1 per fault type
2. Real-Time Capability (15%): Fast-path vs Full-path latency
3. False Alarm Rate Calibration: Empirical alpha guarantee
"""
import argparse
import time
import numpy as np
import pandas as pd
from ather.data.loader import JenaDataLoader
from ather.pipeline import AtherPipeline
from ather.simulator.injector import FaultInjector
from ather.data.schema import AWSReading, FaultType

def run_evaluation(data_path: str = "jena_climate_2009_2016.csv", sample_count: int = 15000):
    print("=" * 70)
    print("      ATHER (SkyGuard AI) — SIH 2026 EVALUATION BENCHMARK")
    print("=" * 70)

    # 1. Load Data
    print(f"\n[1/4] Loading {sample_count} readings from {data_path}...")
    loader = JenaDataLoader(csv_path=data_path)
    df_raw = loader.load_dataframe(nrows=sample_count)
    print(f"      ✓ Loaded {len(df_raw)} records spanning {df_raw['timestamp'].min()} to {df_raw['timestamp'].max()}")

    # Split: 60% Training & Calibration, 40% Injected Evaluation
    split_idx = int(len(df_raw) * 0.6)
    train_df = df_raw.iloc[:split_idx].copy()
    eval_clean_df = df_raw.iloc[split_idx:].reset_index(drop=True).copy()

    # 2. Train & Calibrate
    print("\n[2/4] Fitting multivariate manifolds and calibrating conformal bound...")
    pipeline = AtherPipeline()
    t0 = time.perf_counter()
    pipeline.train_and_calibrate(train_df, calibration_samples=min(4000, len(train_df) - 2000))
    calib_time = time.perf_counter() - t0
    print(f"      ✓ Calibration complete in {calib_time:.2f}s. Conformal quantile: {pipeline.fusion.calibrated_quantile:.4f}")

    # 3. Synthesize Injected Test Bench
    print("\n[3/4] Injecting balanced multi-class sensor fault suite (Merlion TSAD pattern)...")
    injector = FaultInjector(random_seed=42)
    injected_bench = injector.inject_comprehensive_suite(
        eval_clean_df,
        spike_frac=0.015,
        frozen_runs=15,
        drift_runs=10,
        noise_runs=15
    )
    eval_df = injected_bench.data
    ground_truth_labels = injected_bench.anomaly_labels.values
    ground_truth_faults = injected_bench.fault_types.values
    print(f"      ✓ Injected test set: {len(eval_df)} samples ({ground_truth_labels.sum()} anomalous, {(~ground_truth_labels).sum()} clean)")

    # 4. Run Pipeline & Measure Latencies
    print("\n[4/4] Executing detection inference & latency benchmarking...")
    predictions = []
    severities = []
    fault_preds = []
    fast_latencies = []
    full_latencies = []

    for i, row in eval_df.iterrows():
        reading = AWSReading(
            station_id=row["station_id"],
            timestamp=row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"],
            temperature_c=float(row["temperature_c"]),
            pressure_hpa=float(row["pressure_hpa"]),
            humidity_pct=float(row["humidity_pct"]),
            dew_point_c=float(row["dew_point_c"]) if "dew_point_c" in row and pd.notna(row["dew_point_c"]) else None,
            lat=float(row["lat"]),
            lon=float(row["lon"]),
            elevation_m=float(row["elevation_m"])
        )

        # Benchmark full-path inference
        t_full_start = time.perf_counter()
        alert = pipeline.process_reading(reading, fast_path_only=False)
        full_latencies.append((time.perf_counter() - t_full_start) * 1000.0)

        predictions.append(alert.is_anomaly)
        severities.append(alert.severity_score)
        fault_preds.append(alert.root_cause.value)

    # Benchmark isolated fast-path latency on warm-up subset
    fast_pipeline = AtherPipeline()
    for _, row in eval_df.iloc[:400].iterrows():
        r_fast = AWSReading(
            station_id=row["station_id"],
            timestamp=row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"],
            temperature_c=float(row["temperature_c"]),
            pressure_hpa=float(row["pressure_hpa"]),
            humidity_pct=float(row["humidity_pct"]),
            dew_point_c=float(row["dew_point_c"]) if "dew_point_c" in row and pd.notna(row["dew_point_c"]) else None,
            lat=float(row["lat"]),
            lon=float(row["lon"]),
            elevation_m=float(row["elevation_m"])
        )
        t_f0 = time.perf_counter()
        _ = fast_pipeline.process_reading(r_fast, fast_path_only=True)
        fast_latencies.append((time.perf_counter() - t_f0) * 1000.0)

    predictions = np.array(predictions)
    tp = np.sum(predictions & ground_truth_labels)
    fp = np.sum(predictions & ~ground_truth_labels)
    fn = np.sum(~predictions & ground_truth_labels)
    tn = np.sum(~predictions & ~ground_truth_labels)

    precision = tp / max(1, (tp + fp))
    recall = tp / max(1, (tp + fn))
    f1 = 2 * precision * recall / max(1e-6, (precision + recall))
    false_alarm_rate = fp / max(1, (fp + tn))

    print("\n" + "=" * 70)
    print("                    SIH 2026 EVALUATION RESULTS")
    print("=" * 70)
    print(f"  Overall Precision        : {precision * 100:.2f}%")
    print(f"  Overall Recall           : {recall * 100:.2f}%")
    print(f"  Overall F1-Score         : {f1 * 100:.2f}%")
    print(f"  False Alarm Rate (FAR)   : {false_alarm_rate * 100:.3f}% (Target: < 0.100%)")
    print("-" * 70)
    print(f"  Fast-Path Latency (p50)  : {np.median(fast_latencies):.3f} ms")
    print(f"  Fast-Path Latency (p99)  : {np.percentile(fast_latencies, 99):.3f} ms")
    print(f"  Full-Path Latency (p50)  : {np.median(full_latencies):.3f} ms")
    print(f"  Full-Path Latency (p99)  : {np.percentile(full_latencies, 99):.3f} ms")
    print("=" * 70)

    # Breakdown per fault type
    print("\n[Per-Fault Category Detection Rates]")
    print(f"{'Fault Category':<24} | {'Total Injected':<14} | {'Detected':<10} | {'Recall':<8}")
    print("-" * 65)
    for fault_enum in [FaultType.SENSOR_SPIKE, FaultType.FROZEN_SENSOR, FaultType.CALIBRATION_DRIFT, FaultType.NOISE_BURST]:
        mask = (ground_truth_faults == fault_enum.value)
        total_f = np.sum(mask)
        if total_f > 0:
            det = np.sum(predictions[mask])
            rec = (det / total_f) * 100.0
            print(f"{fault_enum.value:<24} | {total_f:<14} | {det:<10} | {rec:.1f}%")
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate ATHER on Jena climate dataset.")
    parser.add_argument("--data", default="jena_climate_2009_2016.csv", help="Path to Jena climate CSV")
    parser.add_argument("--samples", type=int, default=12000, help="Number of samples to evaluate")
    args = parser.parse_args()
    run_evaluation(args.data, args.samples)
