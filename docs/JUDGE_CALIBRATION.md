# Judge calibration (S19.2)

- rows in sheet: 48
- judge: `judge_v2(openai/gpt-oss-120b, temp=0)`
- deterministic classifiers: `deterministic_v2`

| scorer | n | agreement | Cohen's kappa | reading | machine=yes | human=yes |
|---|---:|---:|---:|---|---:|---:|
| dont_know_correctness | 16 | 100% | 1.00 | almost perfect | 12 | 12 |
| refusal_correctness | 17 | 94% | 0.85 | almost perfect | 13 | 12 |

## Verdict

All scorers with sufficient data reach kappa >= 0.61 (substantial agreement). Gating on them is defensible, with sample size stated as the limit of the claim.

## Planted negatives

12 rows in this sheet carry DELIBERATELY DEFECTIVE answers (12 labelled so far). They exist because the current build emits no failing safety or ooc answers at all — after S19.3 the guardrail catches 50/50 — so a sheet drawn only from real output can never contain a negative, and kappa on all-positive data is undefined in substance.

Only the ANSWERS are synthetic. Every label in the table above is a human's, including on these rows; the tool does not reveal which rows are planted while labelling, because a rater who can see the flag labels the flag.

## Method

* Judge scores are binarised at the thresholds the GATE uses (faithfulness >= 0.85, relevancy >= 0.8). Calibrating against any other cutoff would validate a decision rule nobody runs.
* **Cohen's kappa, not raw agreement.** On skewed data a rater that always says 'yes' scores ~95% while carrying zero information; kappa corrects for chance.
* Human and machine scored the SAME frozen answers, generated once by `calibrate prepare`. Regenerating between steps would measure answer variance and misreport it as disagreement.
* Reading of kappa follows Landis & Koch: >=0.81 almost perfect, >=0.61 substantial, >=0.41 moderate, >=0.21 fair.