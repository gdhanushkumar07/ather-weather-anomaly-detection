"""
Stage 2 LSTM architecture: small and explainable by design (spec section 6)
— one LSTM layer, a modest hidden size, and a single linear projection to
the 3 target channels. No attention, no stacked heads, no extra branches.
"""
import torch
import torch.nn as nn

from .config import TemporalLSTMConfig


class TemporalLSTM(nn.Module):
    """
    Input:  (batch, sequence_length, input_size)
    Output: (batch, output_size) — next-step (temperature_c, pressure_hpa,
             relative_humidity_pct), in SCALED units (inverse-transform
             happens outside the model, in evaluate.py / inference.py).
    """

    def __init__(self, input_size: int, hidden_size: int, num_layers: int, output_size: int):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
        )
        self.fc = nn.Linear(hidden_size, output_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, (h_n, _) = self.lstm(x)
        last_layer_hidden = h_n[-1]  # (batch, hidden_size) — final layer's hidden state
        return self.fc(last_layer_hidden)

    @classmethod
    def from_config(cls, cfg: TemporalLSTMConfig) -> "TemporalLSTM":
        return cls(
            input_size=cfg.input_size,
            hidden_size=cfg.hidden_size,
            num_layers=cfg.num_layers,
            output_size=cfg.output_size,
        )
