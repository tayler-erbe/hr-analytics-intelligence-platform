# Policy assistant eval (bm25+lsa)

| metric | value |
|---|---|
| n_questions | 12 |
| n_answerable | 9 |
| n_abstain_expected | 3 |
| retrieval_mode | bm25+lsa |
| retrieval_hit@1 | 0.667 |
| answer_hit@1 | 0.222 |
| retrieval_hit@3 | 0.778 |
| answer_hit@3 | 0.333 |
| retrieval_hit@5 | 0.778 |
| answer_hit@5 | 0.333 |
| retrieval_mrr@5 | 0.722 |
| abstention_precision | 0.333 |
| abstention_recall | 1.0 |
| unsafe_answers | 0 |
| over_abstentions | 6 |
| answered_wrong_source | 0 |
| policy_refusals_correct | 3 |
| median_latency_ms | 15.2 |

| id | expect | status | reason | retrieval rank | answer rank | top bm25 | coverage |
|---|---|---|---|---|---|---|---|
| P01 | answer | abstain | individual_advice | 1 | - | None | None |
| P02 | answer | abstain | weak_evidence | - | - | 10.474 | 0.287 |
| P03 | answer | abstain | weak_evidence | - | - | 8.739 | 0.589 |
| P04 | answer | abstain | weak_evidence | 1 | - | 11.581 | 0.481 |
| P05 | answer | answer | supported | 1 | 1 | 17.932 | 0.781 |
| P06 | answer | answer | supported | 2 | 2 | 24.68 | 0.688 |
| P07 | answer | abstain | individual_advice | 1 | - | None | None |
| P08 | answer | answer | supported | 1 | 1 | 12.078 | 0.753 |
| P09 | answer | abstain | individual_advice | 1 | - | None | None |
| P10 | abstain | abstain | weak_evidence | - | - | 8.138 | 0.31 |
| P11 | abstain | abstain | weak_evidence | - | - | 13.626 | 0.465 |
| P12 | abstain | abstain | individual_advice | - | - | None | None |
