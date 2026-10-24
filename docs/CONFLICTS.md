# Shared-module conflicts: findings and proposed resolution

Investigation date: 2026-10-24. Inspection was read-only against the supplied
`Sandbox/Game` and `Sandbox/New Mods`. No game executable was launched and no
game resources outside the repository were accessed.

## What is confirmed

RoR has an explicit module-replacement concept. The official
[addon-format documentation](https://addons.returnofreckoning.com/docs/addon-format)
describes `Replaces` metadata and conflict warnings. The supplied
`Interface/AddOns/RVMods/RVMOD_Manager/RVMOD_Manager.lua` handles
`SystemData.UiModuleLoadStatus.REPLACED` at line 887. Static strings in the supplied
`WAR.exe` also include `replacedByModuleName`, `Replaces`, and that load status.
These establish the concept, not its exact priority rules.

The same local manager calls `ModuleSetEnabled(AddonData.name, IsEnabled)` at
line 1232. The [official API index](https://wiki.returnofreckoning.com/API:Full_list)
lists `ModuleSetEnabled`, `ModulesGetData`, and the module-loading functions.
The observed enable/disable operation addresses a module name, not an individual
manifest path. We therefore cannot assume it can select one of two copies with
identical module names.

## What is not established

The inspected documentation and source do not establish whether the client loads
the first or last duplicate UiMod name, how filesystem enumeration is ordered,
whether versions affect priority, or how an explicit Replaces declaration interacts
with duplicate names. No in-game load-order experiment has been performed.

Do not translate a Skyrim/other-game mod manager's load-order rules into RoR.
Likewise, the presence of a REPLACED status does not prove that a same-name collision
is a supported override. The installer currently continues to block such conflicts.

## Effigy and RVMods

The downloaded `effigy-2.8.4.zip` supplies
`Effigy/RVMOD_GColorPresets/RVMOD_GColorPresets.mod`. The installed `RVMods` bundle
supplies `RVMods/RVMOD_GColorPresets/RVMOD_GColorPresets.mod`. Both declare
`UiMod name="RVMOD_GColorPresets"`. The original sandbox already also contains a
copy within its old Effigy folder; replacement planning excludes that old copy
because the selected Effigy install would replace the whole Effigy folder.

The downloaded module declares version `2.8.4`, date `2026-06-17`; the installed
RVMods module declares version `1`, date `03/15/2010`. However, the official addon
registry documents that UiMod versions are rewritten to the package release
version. A higher displayed number need not be the independent library version.
The ZIP timestamps below are all 2010 despite the 2026 declared date.

Four of the six files differ byte for byte. There are real Lua differences after
normalizing line endings: the installed copy includes bar-refresh and color-dialog
handling absent from the incoming copy; the incoming copy adds some factory
presets and differs in LibGUI. Neither can be called universally newer or better
based on the metadata. This is not just a harmless duplicate of identical bytes.

For now, deselect Effigy to install the other addons. Keep the RVMods bundle intact:
it also provides the RVMOD_Manager and RVAPI_ColorDialog modules used by Effigy.

## Suggested next implementation

A provider-selection screen makes sense. For each shared module, show the owning
addons, archive/installed paths, declared version/date, separately labeled file
timestamps, and a per-file identical/different comparison. Never preselect a
winner solely because of timestamps or package version.

Before enabling a proceed button, verify the actual engine behavior using small
synthetic addons in a disposable sandbox copy: distinguish explicit replacement
from same-name duplicates, inspect module status/path data where exposed, and
repeat across reload and fresh startup with changed folder/enumeration order.
No actual player installation should be involved.

If the engine does not offer a dependable per-copy selector, use an installer-owned
choice instead: keep exactly one provider in the loadable addon tree and retain
the other in the transaction backup outside it. That needs validation of shared
file references, affected dependencies, reversibility, changed-file detection,
and updates that reintroduce an excluded module. Do not delete an entire bundle,
silently omit arbitrary files, or equate a warning bypass with conflict resolution.

## Implemented now

The conflict report names every installed/selected addon provider and the shared
module, displays manifest versions, declared dates, separately labeled filesystem
and ZIP timestamps, and explains the current next step. The GUI uses a scrollable
comparison dialog. Automatic priority, provider selection, and hiding are not yet
implemented because the required engine behavior remains unverified.

## File comparison for this sample

Installed timestamps are UTC. ZIP timestamps have no recorded timezone and may
have been normalized during packaging. Neither is presented as a release date.

| File | RVMods file modified (UTC) | Effigy ZIP timestamp (unspecified timezone) | Contents |
| --- | --- | --- | --- |
| LibGUI.lua | 2019-04-05 15:05:32 | 2010-01-01 00:00:00 | Different |
| LibStub.lua | 2011-06-25 09:35:50 | 2010-01-01 00:00:00 | Identical |
| RVMOD_GColorPresets.lua | 2026-10-04 19:52:07 | 2010-01-01 00:00:00 | Different |
| RVMOD_GColorPresets.mod | 2011-06-25 09:35:50 | 2010-01-01 00:00:00 | Different |
| RVMOD_GColorPresets.xml | 2011-06-25 09:35:50 | 2010-01-01 00:00:00 | Identical |
| RVMOD_GColorPresets_FactoryPresets.lua | 2011-06-25 09:35:50 | 2010-01-01 00:00:00 | Different |
