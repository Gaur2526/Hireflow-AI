"""Launching calls requires an explicit selection of shortlisted candidates."""

from __future__ import annotations


def test_an_empty_explicit_selection_is_rejected_clearly(client, factory) -> None:
    job = factory.job()
    factory.candidate(job)

    response = client.post(
        f"/api/jobs/{job.id}/campaigns", json={"candidate_ids": []}
    )

    assert response.status_code == 422
    assert "Select at least one shortlisted candidate" in response.json()["error"][
        "message"
    ]
