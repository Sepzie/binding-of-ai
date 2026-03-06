import torch
import torch.nn as nn
import numpy as np
from gymnasium import spaces
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor


class IsaacFeatureExtractor(BaseFeaturesExtractor):
    """
    Custom feature extractor for Isaac observations.

    Processes the grid through a CNN and the player state through an MLP,
    then concatenates the outputs.
    """

    def __init__(self, observation_space: spaces.Dict, features_dim: int = 256):
        # We need to compute the actual features dim, but parent needs it in __init__
        super().__init__(observation_space, features_dim)

        grid_shape = observation_space["grid"].shape  # (C, H, W)
        player_shape = observation_space["player"].shape  # (N,)

        n_channels = grid_shape[0]

        # CNN for grid observations
        self.cnn = nn.Sequential(
            nn.Conv2d(n_channels, 32, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 64, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Flatten(),
        )

        # Compute CNN output size
        with torch.no_grad():
            sample = torch.zeros(1, *grid_shape)
            cnn_out_size = self.cnn(sample).shape[1]

        # MLP for player state
        self.player_mlp = nn.Sequential(
            nn.Linear(player_shape[0], 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU(),
        )

        combined_size = cnn_out_size + 64

        # Final projection to features_dim
        self.fc = nn.Sequential(
            nn.Linear(combined_size, features_dim),
            nn.ReLU(),
        )

        self._features_dim = features_dim

    def forward(self, observations: dict) -> torch.Tensor:
        grid = observations["grid"]
        player = observations["player"]

        cnn_out = self.cnn(grid)
        player_out = self.player_mlp(player)

        combined = torch.cat([cnn_out, player_out], dim=1)
        return self.fc(combined)
