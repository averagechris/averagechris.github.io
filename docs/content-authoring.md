# Content authoring

This is the author-facing map for site content. For tone and agent editing
rules, read [Editorial style](editorial-style.md) first.

## What belongs here

The site is Chris Cummings's personal workshop and publishing home. It can hold
project pages, notes, tools, release/download pages, and personal pages when
they are useful. Software is the center of gravity, but the goal is not to make a
portfolio or a release dashboard wearing a fake mustache.

Write for techy friends and colleagues first. Make relevant pages clear enough
for nontechnical friends and family. Help contributors, netizens, and software
users find what they need. If employers get a useful impression, fine; do not
write primarily for them.

## Source model: Markdown prose plus TOML facts

Canonical content lives under `site-data/`.

- `site-data/site.toml` stores site-level structured facts: title-ish metadata,
  tagline, profile/utility links, and `site.featured_projects`.
- `site-data/home.md` is the published personal homepage prose.
- `site-data/_drafts/home.md` is for unpublished homepage alternatives; moving
  prose into `site-data/home.md` is the publish step.
- `site-data/projects.toml` is the project registry. Its concise `description`
  metadata feeds homepage and Software cards. Keep it short and factual.
- `site-data/projects/<path>.md` is optional fuller prose for that project's
  own page only. Use it for context, non-goals, caveats, or a more human intro;
  do not treat it as the card summary.
- `site-data/projects/_drafts/outline-template.md` is a reusable project-page
  scaffold. Copy from it; do not publish it as-is.
- `site-data/pages/` contains standalone listed pages. Each page has a TOML
  sidecar plus a Markdown or HTML body.
- `site-data/pages/_drafts/` contains unpublished standalone page drafts.
- `site-data/notes/` contains published notes rendered under `/notes/<slug>/`.
- `site-data/notes/_drafts/` contains unpublished note drafts. The checked data
  loader refuses to publish drafts from there.

Use Markdown for prose: explanations, notes, caveats, examples, and links. Use
TOML for structured facts the renderer or tools need to sort, route, validate,
or repeat. If a value is a fact about the site, a project, a slug, a date, or a
link target, it probably belongs in TOML. If it needs voice, rhythm, or context,
it probably belongs in Markdown.

Do not promise a code interface just because it would be nice. If a workflow is
manual today, describe it as manual.

## Homepage, Software cards, and featured order

Homepage prose comes from `site-data/home.md`, not from `site-data/site.toml`.
`site.toml` owns structured facts around that prose: domain, title, name,
description, tagline, links, and the ordered featured project list.

The homepage and Software cards use each project's concise `description` from
`site-data/projects.toml`. Optional project Markdown at
`site-data/projects/<path>.md` is fuller project-page prose. It can expand on
the project, but it should not be the only place a reader can learn the basic
card summary.

Featured project selection and order live in `site.featured_projects` in
`site-data/site.toml`. The legacy `tier = "featured"` entries in
`site-data/projects.toml` mirror that selection only for compatibility; they do
not own the order.

## Draft and publish safety

Drafts are for unfinished thinking. Published directories are for copy Chris is
comfortable putting on the public site.

Before publishing or asking the system to publish:

- remove unresolved `CHRIS:` prompts;
- remove placeholders and TODOs;
- verify factual claims against repo text, release metadata, or another named
  source;
- keep unverified claims out of public copy;
- run the site data check when content files changed:

```sh
PYTHONPATH=scripts python3 -m averagechris_site.data --check
```

Agents never decide that a personal draft is ready. Chris approves; the system
publishes.

### Promoting a Now draft

Now is a standalone page, so its draft is a paired TOML/Markdown set under
`site-data/pages/_drafts/`.

Manual promotion checklist:

1. Move both files out of `site-data/pages/_drafts/` into `site-data/pages/`.
2. In the TOML file, set `draft = false`.
3. Set `listed = true` if the Now page should appear in navigation/listed page
   surfaces.
4. Update `date` to the current published date.
5. Remove every scaffold marker: `CHRIS:`, placeholder text, TODOs, and any
   `UNVERIFIED FACT` block.
6. Validate:

```sh
PYTHONPATH=scripts python3 -m averagechris_site.data --check
```

If any scaffold marker remains, the page is still a draft.

## Agent workflow

Agents editing public copy must:

1. Read [Editorial style](editorial-style.md).
2. State the editing mode: outline/scaffold, proofread, tighten, shape, minimal
   boilerplate, or a named combination.
3. Stay inside the ownership boundaries in the style guide.
4. Mark personal gaps for Chris instead of filling them in.
5. Leave unresolved prompts and unverified blocks unpublished.

Recommended flow:

1. Agent scaffolds the page or section.
2. Chris fills personal answers, anecdotes, opinions, and final claims.
3. Agent proofreads, tightens, or shapes the draft.
4. Chris approves the result.
5. The system publishes.

## Practical patterns

Good page scaffold, noncanonical:

```markdown
+++
title = "Tool name"
slug = "tool-name"
+++

Purpose: introduce the tool without turning it into sales copy.
Reader: technical friend or user who wants to know whether it solves their
problem.

## What it does
[known fact: summarize from README or existing project metadata]

## Why it exists
CHRIS: What repeated annoyance or curiosity led to this?

## Use it if
CHRIS: Name one or two situations where this is genuinely helpful.

## Skip it if
CHRIS: Name one limitation or non-goal.
```

Bad edit:

> This robust and elegant utility empowers users to seamlessly orchestrate their
> workflows.

Better edit:

> This utility runs the release steps in the order this site expects.

Bad agent fill:

> Chris cares deeply about privacy and enterprise-grade security.

Better agent prompt:

> CHRIS: Are there privacy or security constraints worth documenting here? If
> yes, name the concrete behavior rather than a maturity claim.

Bad placeholder in publishable copy:

> TODO: add a funny story about the first version.

Better draft-only prompt:

> CHRIS: Is there a short first-version anecdote that helps readers understand
> why this tool stayed small?
