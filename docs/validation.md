# Validation scope

The portfolio preparation checked Python compilation and the retained `Sensitivity.py --help` entry point. Validation used Python 3.12, PuLP 3.3.2 and its CBC backend in an isolated environment.

A synthetic three-node case was solved with each original formulation. Both runs reported `Optimal`, all constraint residuals were checked with a scale-aware tolerance, integer variables were checked for integrality, and deliveries met the configured penetration target in each period.

| Formulation | Constraints checked | Variables checked | Synthetic objective |
| --- | --- | --- | --- |
| Model 1 | 168 | 138 | €1,019,373 |
| Model 2 | 228 | 168 | €1,952,673 |

The sensitivity pipeline was then exercised on the small case: 15 scenarios completed with finite objective values and optimal statuses, the CSV was produced, and the demand input was restored after the experiment.

These checks establish that the formulations and scenario interfaces operate on a controlled small case. They do not independently validate the national course dataset, resolve the documented historical configuration mismatch, or constitute a new full national run. Archived charts were inspected as historical artifacts rather than claimed as newly regenerated results.
