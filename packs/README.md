# Macro Packs

A **pack** (`.wmbpack`) bundles macros *and* the template images they use into
one shareable file. This is how one engine serves many games — ship (or sell) a
pack per game.

## Using packs in the app
- **Export:** open a folder's `…` menu in the sidebar → **Export as pack…**
- **Import:** sidebar → **Import** → pick a `.wmbpack`

Import drops the macros into a folder named after the pack's game and copies its
templates in (auto-renaming to avoid overwriting anything you already have).
Importing more than the free-tier macro limit prompts a Pro upgrade — so packs
are a natural paid feature.

## What's in this folder
- `summoners-war/` — a **starter** for the next game to support. It is *not*
  plug-and-play: game packs need real screenshots of that game's UI, which must
  be captured on the actual game. Follow its `CAPTURE-GUIDE.md`.

## Building a real pack (the workflow)
1. In the app, make a folder for the game (e.g. "Summoners War").
2. Open the game (Steam client or emulator).
3. Create macros in that folder; use **Capture Region** to grab each button/
   screen the macro reacts to (name them meaningfully — see the guide).
4. Test until the loop runs reliably.
5. Folder `…` menu → **Export as pack…** → you now have a `.wmbpack` to
   distribute or sell.
