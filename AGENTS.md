# Project rules for coding agents

Current tasks, in order: [`CODEX_HANDOFF_EDW_PROFILING.md`](CODEX_HANDOFF_EDW_PROFILING.md) (profile EDW and build calibrated synthetic data), then [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md) (run succession on real data). See [`platform-evaluation/ARCHITECTURE.md`](platform-evaluation/ARCHITECTURE.md) for the folder map.

1. **Data handling.** Real University employee, payroll, HR, survey or position-description data stays on approved machines or inside EDW/Denodo. Never commit it, push it, paste it into chat or send it to a cloud or AI service, unless the University's approval for this tool explicitly covers that data class. Confirm with Tayler before reading real rows.
2. **What Git holds.** Only public data and synthetic data go in Git. Everything under `platform-evaluation/data/` that the `.gitignore` files exclude stays excluded.
3. **No individual scoring.** Outputs are role-, unit- or program-level aggregates with k ≥ 10 and complementary suppression. Person-level scoring stays disabled unless Counsel, the Office for Access and Equity and Illinois HR have signed off (Illinois HB 3773).
4. **Honest reporting.** Never loosen validation gates, thresholds, suppression rules, prompts or scoring to improve results. Changes need a new labelled protocol version. Preserve failed runs, errors and null results.
5. **Frozen assets.** Do not modify `platform-evaluation/benchmark/` (frozen hashes and contracts).
6. **Scope of changes.** Work inside the module you were asked to change, run its tests (`python -m unittest discover -s <module>/tests` from `platform-evaluation/`), and keep other modules unchanged.
7. **Mapping status.** SUCSS → O*NET links are unreviewed suggestions until an HR analyst confirms them. AI-usage data is evidence about tasks, never a job-loss forecast.
