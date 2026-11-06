# NL evaluation: custom_stack_deterministic

Visible development set (not a holdout). Results compare result sets, not LLM judgments.

| metric | value |
|---|---|
| n_questions | 44 |
| n_answerable | 28 |
| n_expected_clarify | 7 |
| n_expected_abstain | 9 |
| behaviour_accuracy | 1.0 |
| result_equality | 1.0 |
| clarification_recall | 1.0 |
| abstention_recall | 1.0 |
| false_clarification | 0.0 |
| false_abstention | 0.0 |
| unsafe_answer_rate | 0.0 |
| clarification_rate | 0.1591 |
| abstention_rate | 0.2045 |
| errors | 0 |
| exact_plan_accuracy | 1.0 |

| id | expected | got | plan exact | result equal |
|---|---|---|---|---|
| Q01 | answer | answer | True | True |
| Q02 | answer | answer | True | True |
| Q03 | answer | answer | True | True |
| Q04 | answer | answer | True | True |
| Q05 | answer | answer | True | True |
| Q06 | answer | answer | True | True |
| Q07 | answer | answer | True | True |
| Q08 | answer | answer | True | True |
| Q09 | answer | answer | True | True |
| Q10 | answer | answer | True | True |
| Q11 | answer | answer | True | True |
| Q12 | answer | answer | True | True |
| Q13 | answer | answer | True | True |
| Q14 | answer | answer | True | True |
| Q15 | answer | answer | True | True |
| Q16 | answer | answer | True | True |
| Q17 | answer | answer | True | True |
| Q18 | answer | answer | True | True |
| Q19 | answer | answer | True | True |
| Q33 | answer | answer | True | True |
| Q34 | answer | answer | True | True |
| Q20 | clarify | clarify |  |  |
| Q21 | clarify | clarify |  |  |
| Q22 | clarify | clarify |  |  |
| Q23 | clarify | clarify |  |  |
| Q24 | clarify | clarify |  |  |
| Q25 | clarify | clarify |  |  |
| Q26 | abstain | abstain |  |  |
| Q27 | abstain | abstain |  |  |
| Q28 | abstain | abstain |  |  |
| Q29 | abstain | abstain |  |  |
| Q30 | abstain | abstain |  |  |
| Q31 | abstain | abstain |  |  |
| Q32 | abstain | abstain |  |  |
| B01 | answer | answer | True | True |
| B02 | answer | answer | True | True |
| B03 | answer | answer | True | True |
| B04 | answer | answer | True | True |
| B05 | answer | answer | True | True |
| B06 | answer | answer | True | True |
| B07 | answer | answer | True | True |
| B08 | clarify | clarify |  |  |
| B09 | abstain | abstain |  |  |
| B10 | abstain | abstain |  |  |
