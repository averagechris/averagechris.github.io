## Purpose and reader

- Purpose: explain how large migrations become safer when the old implementation remains an executable oracle.
- Reader: an engineer replacing a language, runtime, schema system, or execution engine without changing behavior accidentally.
- Public boundary: use synthetic corpora and generic mismatch examples. Do not publish private payloads, schemas, outputs, model capabilities, or migration plans.

## The old system knows more than the documentation

CHRIS: Which semantics were encoded in behavior rather than an explicit specification?

## Build a corpus, not a handful of examples

Known material: deterministic input corpora and stable mismatch categories make parity failures inspectable instead of anecdotal.

CHRIS: How did you choose representative cases without leaking production data?

## Decide what “the same” means

CHRIS: Which differences require exact equality, numerical equivalence, structural parity, or only the same error category?

## Fail closed

CHRIS: How should a prototype behave when it encounters semantics it has not certified?

## When the oracle can retire

CHRIS: What evidence would make you trust the replacement on its own?
