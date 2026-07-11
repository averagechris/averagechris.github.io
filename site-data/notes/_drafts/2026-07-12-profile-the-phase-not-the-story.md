## Purpose and reader

- Purpose: show how a plausible performance diagnosis can fall apart once the work is measured in separate phases.
- Reader: a technical friend who profiles applications, tests, or developer tooling.
- Public boundary: do not name the company, private repositories, domain models, incidents, exact internal measurements, or customer data. Recreate examples with open or synthetic data.

## The first story

CHRIS: What did you initially expect to be slow, and why was that explanation convincing?

## Split the phases

Known material: setup, request execution, database work, imports, startup, and process shutdown can hide very different costs inside one duration.

CHRIS: Which tools or measurements separated the phases clearly enough to change your mind?

## What was actually expensive

CHRIS: Describe the real bottleneck in a generalized, public-safe form.

CHRIS: Which tempting optimization would have improved the wrong phase?

## The reusable lesson

CHRIS: What should another engineer measure before acting on a good performance story?
