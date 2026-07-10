# Editorial style

This site is Chris Cummings's personal workshop and publishing home. Software is
the center of gravity, but the site is not a conventional portfolio and not
primarily a release dashboard. Treat it as a place where projects, notes, small
tools, and occasional personal pages can coexist without turning into LinkedIn
copy.

## Readers, in order

1. Techy friends and colleagues who know enough to enjoy the details.
2. Nontechnical friends and family, when a page is relevant to them.
3. Contributors, netizens, and software users trying to understand or use a
   project.
4. Employers, incidentally and last.

That order matters. A project page may still be useful to a hiring manager, but
it should first sound like Chris explaining useful work to people he respects.

## Voice

Default to technically exact and socially casual.

- Smart without announcing it.
- Funny when the material is naturally funny; never force a bit.
- Common vernacular by default; expansive vocabulary when precision benefits.
- Mature, but not self-serious.
- Direct, specific, and allergic to filler.

Avoid:

- corporate voice, resume voice, hype, thought leadership;
- fake humility, faux-confessional framing, and mandatory punchlines;
- AI-generated quirkiness: whimsical adjectives, overexplained jokes, and
  "delightful little" anything unless Chris wrote it first.

Prefer concrete nouns and verbs. If a sentence could be on a startup landing
page, make it sound like a person again.

## Editing modes for agents

Agents editing public copy must read this guide first and state the editing mode
they are applying. If more than one mode is needed, say so before editing.

### Outline/scaffold

Use when a page or section does not exist yet, or when Chris asks for structure
instead of finished prose.

Allowed:

- propose the page purpose and primary reader;
- offer 2-3 possible angles;
- draft headings and section order;
- ask specific questions;
- prompt for anecdotes, examples, screenshots, links, or evidence;
- include sourced known facts from existing repo/site text.

Required:

- mark all personal answers for Chris with `CHRIS:`;
- mark unknowns, placeholders, and unverified factual blocks clearly;
- keep the scaffold unpublished until Chris fills or approves it.

Unresolved `CHRIS:` prompts, placeholders, TODOs, and unverified factual blocks
are never publishable.

### Proofread

Use when the prose is already Chris's and only correctness needs help.

Allowed: spelling, punctuation, grammar, broken links, Markdown/TOML formatting,
minor clarity fixes that do not change meaning.

Approval: safe to propose as a diff, but Chris still owns publication.

### Tighten

Use when the page says the right thing but drags.

Allowed: cut repetition, remove throat-clearing, shorten sentences, replace
generic phrasing with simpler wording already implied by the text.

Not allowed: adding new claims, changing tone into marketing copy, inventing
jokes, or making Chris sound more certain than the source text.

Approval: Chris must approve before publication.

### Shape

Use when the raw material is present but the page needs structure.

Allowed: reorder sections, split or combine paragraphs, add transitional
sentences, suggest missing evidence, and turn notes into a coherent draft.

Not allowed: inventing biography, motivations, endorsements, security/privacy
claims, maturity claims, anecdotes, opinions, or final project descriptions.

Approval: Chris must review and approve the shaped draft before publication.

### Minimal boilerplate

Use for interface and metadata text where personality is less important than
clarity.

Allowed: section/page/nav labels, instructions, status/error/empty copy,
accessibility labels, factual release boilerplate, and metadata drafts based on
existing prose.

Approval: routine boilerplate may be proposed directly, but anything public and
personal still needs Chris's approval.

## Ownership boundaries

Chris owns biography, Now pages, motivations, endorsements, maturity/security/
privacy claims, personal details, anecdotes, opinions, humor, final project
descriptions, and publication.

Agents may author labels, instructions, status/error/empty copy, accessibility
labels, factual release boilerplate, and metadata drafts when they are grounded
in existing prose or structured facts.

The normal workflow is:

1. Agent scaffolds.
2. Chris fills the personal material.
3. Agent proofreads, tightens, or shapes.
4. Chris approves.
5. The system publishes.

## Examples, noncanonical

Good outline scaffold:

```markdown
Purpose: Explain why this small CLI exists and who should try it.
Primary reader: a technical friend who might use it once and understand the joke.

Angles:
- The tiny annoyance that made the tool worth writing.
- What it automates better than a shell alias.
- What it deliberately does not try to become.

## What it does
[known fact from README: it wraps SourceHut issue queries]

## Why I made it
CHRIS: What was the repeated task or irritation?

## A sharp edge
CHRIS: Is there one limitation users should know before installing?
```

Bad boilerplate:

> Chris is a visionary builder crafting delightful developer experiences at the
> intersection of automation and community.

Better boilerplate:

> Small tools, notes, and release pages from Chris Cummings.

Bad edit:

> I built this because I am obsessed with frictionless workflows.

Better edit, if the source already says this:

> I built this after doing the same release chore one too many times.

Bad status copy:

> Oopsie! The goblins ate this page.

Better status copy:

> This page is not published yet.
