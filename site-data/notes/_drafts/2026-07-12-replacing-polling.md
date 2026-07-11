## Purpose and reader

- Purpose: explain why replacing a polling loop with an event stream is not only a mechanical optimization.
- Reader: an engineer coordinating Kubernetes or another eventually consistent system.
- Public boundary: keep infrastructure generic. Do not publish private clusters, services, topology, polling intervals, incidents, or internal startup measurements.

## Why polling was attractive

CHRIS: What simplicity or diagnostic behavior did the polling loop provide?

## Watching is not the whole implementation

Known material: event-driven waiting still needs deadlines, terminal-state detection, periodic diagnostics, stream-end handling, and recovery from broken watches.

CHRIS: Which edge case would a naïve conversion miss?

## Preserve the breadcrumbs

CHRIS: What should a person see while waiting, and what context should be present when the deadline expires?

## The reusable state machine

CHRIS: What states and transitions make this pattern safer than an ad hoc loop?
