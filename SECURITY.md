# Security and scope

This is an offline file installer, not an addon malware scanner. Addon Lua is
executed later by the game. Only install addons from sources you trust.

The installer validates paths using Windows rules, blocks links/reparse points,
encrypted ZIPs, duplicate names, executable/unknown file types, DTD/entity XML,
and oversized archives. It never executes downloaded files or install scripts.
Archive limits: 256 MiB compressed, 512 MiB expanded, 64 MiB per file, 1 MiB per
manifest, 10,000 entries, and 1000:1 maximum compression ratio per file.

Strict XML parsing is the default. An explicit legacy-syntax option permits only
two in-memory repairs: inserting the missing `xml` keyword in an opening
declaration and escaping literal `<br>` in a standalone `Description text`
attribute. The complete repaired document must still parse as XML; UiMod names,
dependency declarations, and element structure are never guessed or discarded.
DTD/entity and size checks still run first. The mode and accepted repairs are
recorded in review and transaction records. Payload files are installed unchanged.

Only recognized addon trees are mapped into `Interface/AddOns`. Whole UI bundles,
game settings, and game binaries are unsupported. Unknown or ambiguous layouts
fail closed. VinyUI is explicitly blocked, even when renamed if its content still
identifies it; layout checks also reject bundles that modify `user/` settings.
Name detection alone cannot identify every renamed complex bundle.

Replacements require individual approval. The reviewed ZIP is hashed, then copied
and rehashed into a private staging transaction. CRC validation occurs during
extraction. All selected archives are staged before any existing addon is moved.
Changed destinations invalidate approval. Old folders are retained in backups.
Replacement review flags lower numeric versions and unknown comparisons. Free-text
versions are not ordered, and even numeric versions are not compatibility evidence.
Ordinary commit failures trigger rollback; interrupted/crashed transactions require
manual recovery and block subsequent installs. A journal is not a filesystem-wide
atomic transaction or a power-loss guarantee.

Run as your normal user. Do not run concurrently with the game, launcher, another
installer, or tools modifying the same folders. The UI requires confirmation that
the game/launcher are closed; it does not inspect processes. Path checks do not
protect against a hostile local process deliberately swapping filesystem objects
between checks. Do not use network shares or shared, untrusted writable folders.

Dependency checks use UiMod names and required/optional Dependency declarations.
They do not prove runtime compatibility, enabled state, version constraints,
undeclared Lua requirements, or the safety of an addon. Built-in EA-prefixed
modules are assumed available. Existing malformed manifests are reported.

Report reproducible safety issues privately to the repository maintainer via
GitHub's private vulnerability reporting if enabled. Do not post private game
profiles or proprietary game resources in issues. Include a minimal synthetic ZIP,
expected behavior, and the transaction record with local paths redacted.
