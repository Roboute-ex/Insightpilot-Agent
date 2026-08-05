from __future__ import annotations


def test_every_recommendation_references_existing_evidence(transaction_result) -> None:
    package = transaction_result["analysis_result_package"]
    evidence_ids = {item["evidence_id"] for item in package["evidence"]}
    assert package["recommendations"]
    for recommendation in package["recommendations"]:
        assert recommendation["supporting_evidence_ids"]
        assert set(recommendation["supporting_evidence_ids"]).issubset(evidence_ids)
