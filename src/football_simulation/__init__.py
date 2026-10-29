"""Football Match Digital Twin & Simulation System (V1).

A world-model based football match simulation engine:

    Data -> World Model -> Team/Coach/Player/Tactical State
         -> Scenario Generation -> State Transition -> Event Simulation
         -> Monte Carlo Aggregation -> Probability Output -> Risk / Explanation

Core philosophy: **Predict less, simulate more.**

All probabilities are stored internally in the 0..1 range; presentation layers
may convert to percentages.
"""

__version__ = "1.0.0"
