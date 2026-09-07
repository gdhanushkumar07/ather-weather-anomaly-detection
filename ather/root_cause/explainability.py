"""
Explainability (XAI) Engine.
Synthesizes SHAP feature attributions and multi-layer evidence into clear,
actionable natural language diagnoses for AWS field engineers and meteorologists.
"""
from typing import Dict, List, Optional
from ather.data.schema import AWSReading, FaultType

class ExplanationGenerator:
    """
    Transforms quantitative detection scores and layer diagnostics into human-interpretable explanations.
    """
    def generate_explanation(
        self,
        reading: AWSReading,
        fault_type: FaultType,
        layer_scores: Dict[str, float],
        reasons: List[str],
        sensor_health: float,
        days_to_failure: Optional[float]
    ) -> str:
        """
        Synthesizes a structured plain-language explanation for an AWS alert.
        """
        if fault_type == FaultType.NORMAL:
            return f"Station {reading.station_id}: All sensors operating within normal nominal parameters (Health: {sensor_health:.1f}%)."

        if fault_type == FaultType.GENUINE_EXTREME_WEATHER:
            return (
                f"METEOROLOGICAL EVENT DETECTED at {reading.station_id}: Sharp atmospheric shifts observed "
                f"(Temp: {reading.temperature_c:.1f}°C, Pressure: {reading.pressure_hpa:.1f}hPa, RH: {reading.humidity_pct:.1f}%), "
                f"but regional neighbor stations corroborate the trend and thermodynamic laws remain valid. "
                f"ACTION: Flagged as genuine severe weather, NOT a hardware malfunction."
            )

        # Build diagnostic breakdown
        reasons_summary = "; ".join(reasons) if reasons else "Multiple layer thresholds exceeded"

        # Identify dominant layer
        dominant_layer = max(layer_scores.items(), key=lambda x: x[1]) if layer_scores else ("none", 0.0)

        action_map = {
            FaultType.SENSOR_SPIKE: "Transient impulse error detected. Check cable shielding and power supply grounding.",
            FaultType.FROZEN_SENSOR: "ADC lockup or physical debris obstructing sensor transducer. Dispatch field technician to unstick/power-cycle sensor.",
            FaultType.CALIBRATION_DRIFT: f"Systematic calibration bias accumulating. Recalibrate transducer against secondary reference.",
            FaultType.NOISE_BURST: "High-frequency interference detected. Inspect analog wiring and radio antenna proximity.",
            FaultType.SINGLE_CHANNEL_FAULT: "Channel disconnected or reporting impossible physical readings. Replace sensor module immediately.",
            FaultType.COMMUNICATION_OUTAGE: "Data loss in transmission. Check cellular/LoRa gateway connection."
        }

        action_recommendation = action_map.get(fault_type, "Inspect station hardware.")
        if days_to_failure is not None and days_to_failure < 7.0:
            action_recommendation += f" URGENT: Projected WMO tolerance breach in {days_to_failure:.1f} days."

        explanation = (
            f"[{fault_type.value}] at {reading.station_id} — Primary trigger: {dominant_layer[0].capitalize()} Layer "
            f"(Score: {dominant_layer[1]:.2f}). Evidence: {reasons_summary}. "
            f"Station Health: {sensor_health:.1f}%. Recommended Action: {action_recommendation}"
        )
        return explanation
