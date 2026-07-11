## Purpose and reader

- Purpose: resist the easy conclusion that a faster language automatically explains a successful rewrite.
- Reader: an engineer considering a hot-path rewrite.
- Public boundary: describe a generic rules or calculation engine. Do not publish protected models, domain inputs, exact benchmarks, rollout plans, or private APIs.

## The tempting headline

CHRIS: What made “Rust is faster” feel like an adequate explanation at first?

## The execution model changed too

Known material: eager materialization, composite indexes, candidate selection, and removal of impossible rows can change the problem before language speed enters the picture.

CHRIS: Which data-layout change produced the most surprising result?

CHRIS: How would you separate gains from the language, runtime, algorithm, and representation?

## Correctness before celebration

CHRIS: What parity or differential-testing gate made the comparison credible?

## The honest conclusion

CHRIS: What advice would you give someone reaching for a rewrite before profiling data access?
