"""Simulation lab service: runs what-if scenarios on the SYNTHETIC simulator (see ml/simulation/lab.py).

Cost is bounded three ways: the request schema caps doctors/days/scenarios, the simulator is a fast
pure-Python loop, and at most two simulations run at the same time per process (others get a 429).
Nothing is read from or written to the clinic's data.
"""
from __future__ import annotations

import threading

from app.core.errors import ServiceError
from app.schemas.simulation import OutcomeOut, ScenarioIn, ScenarioResult, SimulationIn, SimulationOut
from ml.simulation.lab import Scenario, outcome_dict, run

_slots = threading.BoundedSemaphore(2)

NOTE = ("Synthetic what-if on a generic queue simulator using the settings you gave. It is not a forecast of "
        "this clinic: it knows nothing about your real patients, and each simulated doctor has their own "
        "queue, so it cannot model adding staff. Use it to compare how sensitive waits are to a change, "
        "not to predict actual waits.")


def simulate(body: SimulationIn) -> SimulationOut:
    if not _slots.acquire(blocking=False):
        raise ServiceError(429, "The simulation lab is busy. Please try again in a moment.")
    try:
        results: list[ScenarioResult] = []
        first = None
        for scenario in body.scenarios:
            outcome = run(Scenario(**scenario.model_dump()))
            first = first or outcome
            is_first = outcome is first
            results.append(ScenarioResult(
                scenario=ScenarioIn(**scenario.model_dump()), outcome=OutcomeOut(**outcome_dict(outcome)),
                mean_wait_change_minutes=None if is_first else round(outcome.mean_wait_minutes - first.mean_wait_minutes, 2),
                p90_wait_change_minutes=None if is_first else round(outcome.p90_wait_minutes - first.p90_wait_minutes, 2),
                utilisation_change=None if is_first else round(outcome.utilisation - first.utilisation, 4)))
        return SimulationOut(results=results, note=NOTE)
    finally:
        _slots.release()
