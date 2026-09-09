"""
Explainability (XAI) Engine (v2).

BUG FIXES (v2):
  - Operator actions are now gated by diagnosis confidence.
  - HIGH evidence only: strong prescriptive language.
  - MEDIUM evidence: conditional language, monitoring emphasis.
  - LOW / INSUFFICIENT_DATA: no prescriptive action — observe and verify.
  - Never outputs "Replace sensor immediately" unless evidence is HIGH confidence.
  - Explanation includes actual measured values where available.
"""
from typing import Dict, List, Optional
from schema import AWSReading, FaultType, DiagnosisConfidence


class ExplanationGenerator:
    """
    Translates diagnosis result and layer evidence into human-readable explanations.
    """

    def generate_explanation(
        self,
        reading:             AWSReading,
        fault_type:          FaultType,
        diagnosis_confidence: DiagnosisConfidence,
        layer_scores:        Dict[str, float],
        reasons:             List[str],
        sensor_health:       float,
        days_to_failure:     Optional[float],
        primary_signal:      str = "",
        alternatives:        Optional[List[str]] = None,
        layer_details:       Optional[Dict] = None,
    ) -> str:
        """
        Generates a structured natural-language explanation grounded in actual values.
        """
        alternatives  = alternatives or []
        layer_details = layer_details or {}
        stn_id        = reading.station_id

        # ── Normal ─────────────────────────────────────────────────────────
        if fault_type == FaultType.NORMAL:
            channels_ok = []
            if reading.temperature_c is not None:
                channels_ok.append(f"temperature {reading.temperature_c:.1f}°C")
            if reading.pressure_hpa is not None:
                channels_ok.append(f"pressure {reading.pressure_hpa:.1f} hPa")
            if reading.humidity_pct is not None:
                channels_ok.append(f"humidity {reading.humidity_pct:.1f}%")
            ch_str = ", ".join(channels_ok) if channels_ok else "available channels"
            return f"All sensors within normal operating limits ({ch_str}). Sensor health: {sensor_health:.0f}%."

        # ── Build observed value summary ───────────────────────────────────
        obs_parts = []
        if reading.temperature_c is not None and reading.channel_valid("temperature_c"):
            obs_parts.append(f"T={reading.temperature_c:.1f}°C")
        if reading.pressure_hpa is not None and reading.channel_valid("pressure_hpa"):
            obs_parts.append(f"P={reading.pressure_hpa:.1f} hPa")
        if reading.humidity_pct is not None and reading.channel_valid("humidity_pct"):
            obs_parts.append(f"RH={reading.humidity_pct:.1f}%")

        obs_str  = ", ".join(obs_parts) if obs_parts else "some channels have missing data"
        ev_str   = "; ".join(reasons[:3]) if reasons else primary_signal

        # ── Confidence-gated action language ──────────────────────────────
        if diagnosis_confidence == DiagnosisConfidence.HIGH:
            certainty_word = "Likely"
            action_prefix  = ""
        elif diagnosis_confidence == DiagnosisConfidence.MEDIUM:
            certainty_word = "Possible"
            action_prefix  = "If confirmed: "
        elif diagnosis_confidence == DiagnosisConfidence.LOW:
            certainty_word = "Potential (low confidence)"
            action_prefix  = "Suggested: "
        else:  # INSUFFICIENT_DATA
            certainty_word = "Uncertain"
            action_prefix  = "If it continues: "

        # ── Fault-type specific explanation ───────────────────────────────
        if fault_type == FaultType.GENUINE_EXTREME_WEATHER:
            return (
                f"{stn_id}: Real meteorological event likely. "
                f"Observed: {obs_str}. "
                f"Evidence: {ev_str}. "
                f"Nearby stations show similar conditions — not a sensor issue. "
                f"Sensor health: {sensor_health:.0f}%."
            )

        if fault_type == FaultType.POSSIBLE_WEATHER_CHANGE:
            return (
                f"{stn_id}: Rapid change recorded. "
                f"Observed: {obs_str}. "
                f"Evidence: {ev_str}. "
                f"Insufficient spatial data to determine if this is regional weather or a station-level anomaly. "
                f"Monitor nearby stations for comparison."
            )

        if fault_type == FaultType.FROZEN_SENSOR:
            return (
                f"{certainty_word} frozen sensor at {stn_id}. "
                f"Observed: {obs_str}. "
                f"Evidence: {ev_str}. "
                f"Sensor health: {sensor_health:.0f}%. "
                f"{action_prefix}Inspect sensor for physical obstruction or ADC lockup."
            )

        if fault_type == FaultType.SENSOR_SPIKE:
            alt_str = f" Alternative: {alternatives[0]}." if alternatives else ""
            return (
                f"{certainty_word} sensor transient at {stn_id}. "
                f"Observed: {obs_str}. "
                f"Evidence: {ev_str}.{alt_str} "
                f"Sensor health: {sensor_health:.0f}%. "
                f"{action_prefix}Check sensor cable and power supply. "
                f"Confirm with next observation."
            )

        if fault_type == FaultType.CALIBRATION_DRIFT:
            dtf_str = (
                f" Projected tolerance breach in {days_to_failure:.0f} days."
                if days_to_failure is not None and days_to_failure < 30 else ""
            )
            return (
                f"{certainty_word} calibration drift at {stn_id}. "
                f"Observed: {obs_str}. "
                f"Evidence: {ev_str}.{dtf_str} "
                f"Sensor health: {sensor_health:.0f}%. "
                f"{action_prefix}Compare with secondary reference sensor."
            )

        if fault_type == FaultType.SINGLE_CHANNEL_FAULT:
            return (
                f"{certainty_word} station-level discrepancy at {stn_id}. "
                f"Observed: {obs_str}. "
                f"Evidence: {ev_str}. "
                f"Station diverges from neighbouring measurements. "
                f"Sensor health: {sensor_health:.0f}%. "
                f"{action_prefix}Inspect and compare with nearby stations."
            )

        if fault_type == FaultType.NOISE_BURST:
            return (
                f"{certainty_word} measurement noise at {stn_id}. "
                f"Observed: {obs_str}. "
                f"Evidence: {ev_str}. "
                f"This may self-resolve. "
                f"{action_prefix}Monitor next reading."
            )

        if fault_type == FaultType.INSUFFICIENT_EVIDENCE:
            return (
                f"Anomaly threshold reached at {stn_id}, but evidence is limited. "
                f"Observed: {obs_str}. "
                f"Available signal: {ev_str if ev_str else 'no specific pattern identified'}. "
                f"Sensor health: {sensor_health:.0f}%. "
                f"Monitor closely over the next few observations."
            )

        if fault_type == FaultType.COMMUNICATION_OUTAGE:
            return f"Data communication disruption at {stn_id}. No valid sensor readings received."

        # Generic fallback
        return (
            f"Anomaly at {stn_id}. Observed: {obs_str}. "
            f"Evidence: {ev_str}. "
            f"Sensor health: {sensor_health:.0f}%."
        )

    def generate_operator_action(
        self,
        fault_type:           FaultType,
        diagnosis_confidence: DiagnosisConfidence,
        days_to_failure:      Optional[float],
        layer_details:        Optional[Dict] = None,
    ) -> str:
        """
        Returns a confidence-gated operator action recommendation.
        NEVER prescribes hardware replacement for low/medium evidence.
        """
        if fault_type == FaultType.NORMAL or fault_type == FaultType.INSUFFICIENT_EVIDENCE:
            return "Monitor. No immediate action required."

        if diagnosis_confidence == DiagnosisConfidence.INSUFFICIENT_DATA:
            return "Observe the next several readings before taking action."

        if diagnosis_confidence == DiagnosisConfidence.LOW:
            return "Monitor closely. Compare with neighboring stations. No hardware action yet."

        # MEDIUM confidence
        if diagnosis_confidence == DiagnosisConfidence.MEDIUM:
            action_map = {
                FaultType.SENSOR_SPIKE:         "Verify sensor data against neighbours. If repeated, schedule inspection.",
                FaultType.FROZEN_SENSOR:        "Attempt remote power-cycle if supported. If unresponsive, schedule field visit.",
                FaultType.CALIBRATION_DRIFT:    "Compare against secondary reference. If confirmed, schedule recalibration.",
                FaultType.NOISE_BURST:          "Monitor. Check antenna and cable shielding if recurring.",
                FaultType.SINGLE_CHANNEL_FAULT: "Inspect and cross-check against nearby stations.",
                FaultType.GENUINE_EXTREME_WEATHER: "No hardware action. Monitor for storm damage.",
                FaultType.POSSIBLE_WEATHER_CHANGE: "Compare with nearby stations before acting.",
            }
            base = action_map.get(fault_type, "Investigate and monitor.")
            if days_to_failure is not None and days_to_failure < 7:
                base += f" Note: projected tolerance breach in {days_to_failure:.0f} days."
            return base

        # HIGH confidence
        action_map_high = {
            FaultType.SENSOR_SPIKE:         "Check cable shielding and power supply. Replace if recurring.",
            FaultType.FROZEN_SENSOR:        "Power-cycle the sensor. If still frozen, replace transducer.",
            FaultType.CALIBRATION_DRIFT:    "Recalibrate against secondary reference. Plan sensor replacement if drift is severe.",
            FaultType.NOISE_BURST:          "Inspect analog wiring and RF interference sources.",
            FaultType.SINGLE_CHANNEL_FAULT: "Channel appears disconnected or reporting impossible values. Inspect sensor module.",
            FaultType.GENUINE_EXTREME_WEATHER: "No action — real severe weather. Inspect for storm damage post-event.",
            FaultType.POSSIBLE_WEATHER_CHANGE: "Monitor. Compare with regional NWP data.",
        }
        base = action_map_high.get(fault_type, "Inspect station hardware.")
        if days_to_failure is not None and days_to_failure < 7:
            base += f" URGENT: Projected tolerance breach in {days_to_failure:.0f} days."
        return base
