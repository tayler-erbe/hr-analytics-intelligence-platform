# Policy assistant eval (bm25+lsa)

| metric | value |
|---|---|
| n_questions | 40 |
| n_answerable | 30 |
| n_abstain_expected | 10 |
| retrieval_mode | bm25+lsa |
| retrieval_hit@1 | 0.867 |
| answer_hit@1 | 0.867 |
| retrieval_hit@3 | 0.933 |
| answer_hit@3 | 0.933 |
| retrieval_hit@5 | 1.0 |
| answer_hit@5 | 0.967 |
| retrieval_mrr@5 | 0.917 |
| abstention_precision | 0.9 |
| abstention_recall | 0.9 |
| unsafe_answers | 1 |
| over_abstentions | 1 |
| answered_wrong_source | 0 |
| policy_refusals_correct | 6 |
| median_latency_ms | 12.7 |

| id | expect | status | reason | retrieval rank | answer rank | top bm25 | coverage |
|---|---|---|---|---|---|---|---|
| A01 | answer | answer | supported | 1 | 1 | 23.162 | 1.0 |
| A02 | answer | answer | supported | 1 | 1 | 12.58 | 1.0 |
| A03 | answer | answer | supported | 1 | 1 | 28.758 | 1.0 |
| A04 | answer | answer | supported | 1 | 1 | 34.18 | 0.978 |
| A05 | answer | answer | supported | 1 | 1 | 22.255 | 1.0 |
| A06 | answer | answer | supported | 4 | 4 | 32.545 | 1.0 |
| A07 | answer | answer | supported | 1 | 1 | 29.265 | 0.923 |
| A08 | answer | answer | supported | 1 | 1 | 24.645 | 1.0 |
| A09 | answer | answer | supported | 1 | 1 | 47.925 | 0.872 |
| A10 | answer | answer | supported | 1 | 1 | 18.68 | 1.0 |
| A11 | answer | answer | supported | 1 | 1 | 18.68 | 0.954 |
| A12 | answer | answer | supported | 1 | 1 | 16.302 | 0.805 |
| A13 | answer | answer | supported | 1 | 1 | 15.7 | 1.0 |
| A14 | answer | answer | supported | 1 | 1 | 19.149 | 0.78 |
| A15 | answer | answer | supported | 1 | 1 | 14.481 | 0.664 |
| A16 | answer | answer | supported | 1 | 1 | 17.837 | 0.74 |
| A17 | answer | abstain | weak_evidence | 4 | - | 11.926 | 0.435 |
| A18 | answer | answer | supported | 1 | 1 | 14.913 | 0.641 |
| A19 | answer | answer | supported | 1 | 1 | 12.747 | 1.0 |
| A20 | answer | answer | supported | 1 | 1 | 13.164 | 1.0 |
| A21 | answer | answer | supported | 1 | 1 | 34.376 | 1.0 |
| A22 | answer | answer | supported | 1 | 1 | 13.81 | 1.0 |
| A23 | answer | answer | supported | 1 | 1 | 22.363 | 1.0 |
| A24 | answer | answer | supported | 1 | 1 | 22.722 | 0.859 |
| A25 | answer | answer | supported | 1 | 1 | 21.279 | 1.0 |
| A26 | answer | answer | supported | 1 | 1 | 21.55 | 1.0 |
| A27 | answer | answer | supported | 2 | 2 | 17.116 | 0.769 |
| A28 | answer | answer | supported | 1 | 1 | 23.239 | 0.829 |
| A29 | answer | answer | supported | 1 | 1 | 27.308 | 1.0 |
| A30 | answer | answer | supported | 2 | 2 | 20.516 | 1.0 |
| U01 | abstain | abstain | weak_evidence | - | - | 15.172 | 0.434 |
| U02 | abstain | answer | supported | - | - | 10.676 | 0.823 |
| U03 | abstain | abstain | weak_evidence | - | - | 6.263 | 0.094 |
| U04 | abstain | abstain | weak_evidence | - | - | 9.473 | 0.245 |
| U05 | abstain | abstain | weak_evidence | - | - | 8.048 | 0.455 |
| U06 | abstain | abstain | individual_advice | - | - | None | None |
| U07 | abstain | abstain | employment_decision | - | - | None | None |
| U08 | abstain | abstain | legal_determination | - | - | None | None |
| U09 | abstain | abstain | employment_decision | - | - | None | None |
| U10 | abstain | abstain | personal_data | - | - | None | None |
