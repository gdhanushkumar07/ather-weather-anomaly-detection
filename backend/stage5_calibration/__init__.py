"""
ATHER Temporal Intelligence — Stage 5: calibration, validation, and
fusion-compatibility analysis for the Stage 4 integrated TemporalPatternLayer.

Stage 5 is ANALYSIS ONLY unless calibration results explicitly justify a
minimal, documented production change. It does NOT retrain the LSTM,
does NOT modify Stage 1-3 artifacts, and does NOT redesign Evidence
Fusion. It reads the Stage 1 normal dataset and Stage 3 injected-anomaly
dataset (both read-only) and runs the FROZEN Stage 4 production
TemporalPatternLayer against them to measure real behavior instead of
assuming it.

LIMITATION: every measurement here is against SYNTHETIC Stage 1/3 data.
Nothing in this package's output may be presented as real-world AWS
detection accuracy — see stage5_results/*.json's own disclaimers.
"""
