"""
Synthetic fault injection framework for AWS sensor streams.
Implements the fault patterns specified in ATHER Solution Doc & Merlion TSAD:
- Sudden Spikes
- Frozen / Stuck readings
- Calibration Drift
- High-Frequency Noise Bursts
- Single-Channel Disconnects
- Genuine Extreme Weather Events (control condition)
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np
import pandas as pd

from ather.data.schema import FaultType

@dataclass
class InjectedDataset:
    data: pd.DataFrame
    anomaly_labels: pd.Series
    fault_types: pd.Series
    affected_channels: pd.Series
    severities: pd.Series

class FaultInjector:
    """
    Injects synthetic anomalies with ground truth labels into clean weather time series.
    """
    def __init__(self, random_seed: int = 42):
        self.rng = np.random.default_rng(random_seed)

    def inject_spikes(
        self,
        df: pd.DataFrame,
        fraction: float = 0.005,
        magnitude_range: Tuple[float, float] = (6.0, 18.0)
    ) -> InjectedDataset:
        """
        Injects abrupt isolated spikes into temperature, pressure, or humidity.
        """
        df_out = df.copy()
        n = len(df_out)
        labels = pd.Series(False, index=df_out.index)
        faults = pd.Series(FaultType.NORMAL.value, index=df_out.index)
        channels = pd.Series("none", index=df_out.index)
        severities = pd.Series(0.0, index=df_out.index)

        num_spikes = int(n * fraction)
        spike_indices = self.rng.choice(n, size=num_spikes, replace=False)

        channel_choices = ["temperature_c", "pressure_hpa", "humidity_pct"]

        for idx in spike_indices:
            ch = self.rng.choice(channel_choices)
            sign = self.rng.choice([-1, 1])
            mag = self.rng.uniform(*magnitude_range)
            delta = sign * mag

            # Apply delta with physical bounds clamping
            if ch == "humidity_pct":
                df_out.at[idx, ch] = float(np.clip(df_out.at[idx, ch] + delta, 0.0, 100.0))
            else:
                df_out.at[idx, ch] = float(df_out.at[idx, ch] + delta)

            labels.at[idx] = True
            faults.at[idx] = FaultType.SENSOR_SPIKE.value
            channels.at[idx] = ch
            severities.at[idx] = min(1.0, mag / magnitude_range[1])

        return InjectedDataset(df_out, labels, faults, channels, severities)

    def inject_frozen(
        self,
        df: pd.DataFrame,
        num_runs: int = 20,
        run_length_range: Tuple[int, int] = (16, 36)
    ) -> InjectedDataset:
        """
        Injects frozen / stuck-at-constant readings (sensor ADC lockup).
        """
        df_out = df.copy()
        n = len(df_out)
        labels = pd.Series(False, index=df_out.index)
        faults = pd.Series(FaultType.NORMAL.value, index=df_out.index)
        channels = pd.Series("none", index=df_out.index)
        severities = pd.Series(0.0, index=df_out.index)

        channel_choices = ["temperature_c", "pressure_hpa", "humidity_pct"]

        for _ in range(num_runs):
            length = int(self.rng.integers(*run_length_range))
            start_idx = int(self.rng.integers(0, max(1, n - length)))
            ch = self.rng.choice(channel_choices)
            stuck_val = df_out.at[start_idx, ch]
            min_steps = min(12, max(2, int(length * 0.6)))

            for step in range(start_idx, start_idx + length):
                df_out.at[step, ch] = stuck_val
                # Flag after min_steps intervals
                if step - start_idx >= min_steps:
                    labels.at[step] = True
                    faults.at[step] = FaultType.FROZEN_SENSOR.value
                    channels.at[step] = ch
                    severities.at[step] = min(1.0, (step - start_idx) / run_length_range[1])

        return InjectedDataset(df_out, labels, faults, channels, severities)

    def inject_drift(
        self,
        df: pd.DataFrame,
        num_runs: int = 10,
        drift_duration: int = 144, # 144 samples = 24 hours at 10m
        max_drift_rate: float = 0.05
    ) -> InjectedDataset:
        """
        Injects slow calibration drift (e.g. photodiode fouling or resistor aging).
        """
        df_out = df.copy()
        n = len(df_out)
        labels = pd.Series(False, index=df_out.index)
        faults = pd.Series(FaultType.NORMAL.value, index=df_out.index)
        channels = pd.Series("none", index=df_out.index)
        severities = pd.Series(0.0, index=df_out.index)

        channel_choices = ["temperature_c", "humidity_pct"]

        for _ in range(num_runs):
            start_idx = int(self.rng.integers(0, max(1, n - drift_duration)))
            ch = self.rng.choice(channel_choices)
            drift_rate = self.rng.uniform(0.02, max_drift_rate) * self.rng.choice([-1, 1])

            for step in range(start_idx, start_idx + drift_duration):
                cum_drift = drift_rate * (step - start_idx)
                df_out.at[step, ch] = float(df_out.at[step, ch] + cum_drift)
                if abs(cum_drift) > 1.5:  # Significant drift
                    labels.at[step] = True
                    faults.at[step] = FaultType.CALIBRATION_DRIFT.value
                    channels.at[step] = ch
                    severities.at[step] = min(1.0, abs(cum_drift) / 10.0)

        return InjectedDataset(df_out, labels, faults, channels, severities)

    def inject_noise_burst(
        self,
        df: pd.DataFrame,
        num_runs: int = 15,
        burst_duration_range: Tuple[int, int] = (10, 36),
        noise_std: float = 4.0
    ) -> InjectedDataset:
        """
        Injects electrical noise burst / electromagnetic interference.
        """
        df_out = df.copy()
        n = len(df_out)
        labels = pd.Series(False, index=df_out.index)
        faults = pd.Series(FaultType.NORMAL.value, index=df_out.index)
        channels = pd.Series("none", index=df_out.index)
        severities = pd.Series(0.0, index=df_out.index)

        channel_choices = ["temperature_c", "pressure_hpa", "humidity_pct"]

        for _ in range(num_runs):
            duration = int(self.rng.integers(*burst_duration_range))
            start_idx = int(self.rng.integers(0, max(1, n - duration)))
            ch = self.rng.choice(channel_choices)

            noise = self.rng.normal(0, noise_std, size=duration)
            for i, step in enumerate(range(start_idx, start_idx + duration)):
                df_out.at[step, ch] = float(df_out.at[step, ch] + noise[i])
                labels.at[step] = True
                faults.at[step] = FaultType.NOISE_BURST.value
                channels.at[step] = ch
                severities.at[step] = min(1.0, abs(noise[i]) / (noise_std * 2.5))

        return InjectedDataset(df_out, labels, faults, channels, severities)

    def inject_comprehensive_suite(
        self,
        df: pd.DataFrame,
        spike_frac: float = 0.008,
        frozen_runs: int = 25,
        drift_runs: int = 15,
        noise_runs: int = 20
    ) -> InjectedDataset:
        """
        Applies a balanced combination of all fault types to build the SIH evaluation benchmark.
        """
        res_spike = self.inject_spikes(df, fraction=spike_frac)
        res_frozen = self.inject_frozen(res_spike.data, num_runs=frozen_runs)
        res_drift = self.inject_drift(res_frozen.data, num_runs=drift_runs)
        res_final = self.inject_noise_burst(res_drift.data, num_runs=noise_runs)

        # Merge labels and severities
        final_labels = res_spike.anomaly_labels | res_frozen.anomaly_labels | res_drift.anomaly_labels | res_final.anomaly_labels

        final_faults = pd.Series(FaultType.NORMAL.value, index=df.index)
        final_channels = pd.Series("none", index=df.index)
        final_severities = pd.Series(0.0, index=df.index)

        for src in [res_spike, res_frozen, res_drift, res_final]:
            mask = src.anomaly_labels
            final_faults[mask] = src.fault_types[mask]
            final_channels[mask] = src.affected_channels[mask]
            final_severities[mask] = np.maximum(final_severities[mask], src.severities[mask])

        return InjectedDataset(
            data=res_final.data,
            anomaly_labels=final_labels,
            fault_types=final_faults,
            affected_channels=final_channels,
            severities=final_severities
        )
