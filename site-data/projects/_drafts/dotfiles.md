My dotfiles manage an extremely intricate setup across all of my machines. I would wager that it is easily a hundred times more intricate than what most of my colleagues run, which is usually the part that surprises them.

That is a little less surprising in the agentic era, except I do not spend any tokens maintaining it. Nix makes the whole thing mechanically reproducible and portable. I can make my computers work exactly how I want, without having to remember how I got there. The declarative code that builds the system is also the documentation for it. It is like Terraform for personal computers, except way better.

## What is worth borrowing

I am mostly done shilling Nix to people who are reluctant to try it. I still think it is worth the effort, but nobody needs to adopt my entire operating-system religion to get something useful from this repository.

In the current era, I would start with my OpenCode setup. The WezTerm configuration is also cool. More broadly, I use the same keybinding strategy throughout the system, and I think it is incredibly ergonomic.

CHRIS: Explain the keybinding strategy in one concrete example. What stays consistent between the shell, terminal, editor, window management, or other tools?

CHRIS: Name two or three OpenCode ideas or files that someone can borrow without adopting the whole flake.

## The overengineered parts

The shell setup is probably the silliest overengineered part. The OpenCode patches are also strong contenders.

CHRIS: What does the shell setup do that makes this answer funny rather than merely complicated?

CHRIS: Which OpenCode patch best demonstrates “the software should work exactly how I want”?

## Do not copy this blindly

CHRIS: Which parts are tightly coupled to your machines, hostnames, accounts, or personal habits?

CHRIS: What should a reader understand before treating this as a starter configuration rather than a source of ideas?
