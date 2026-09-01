# Unsupported Actors — Audit
_Audited April 2026 from goal_src/jak1/ — all types with init-from-entity! not in ENTITY_DEFS_
_Updated April 2026: addon now covers 147 actor types after feature/lumps session_

**Addon coverage as of feature/lumps merge:** 147 actor types  
**Status:** Most Tier 1 and Tier 2 non-prop actors implemented. Prop batch (~30) deferred.  
**Remaining missing placeable actors:** ~100 (mostly props, Tier 3 complex systems, Tier 4)  

Actors are grouped by category and complexity. "Complexity" is a rough estimate of
effort to add to ENTITY_DEFS and get working in a custom level.

---

## Priority Tiers

**Tier 1 — Easy wins** (generic props/decorations, no special lumps, just need art group)  
**Tier 2 — Moderate** (read a few lumps, need testing)  
**Tier 3 — Complex** (multi-actor systems, spline paths, level-specific logic)  
**Tier 4 — Unlikely** (cutscene actors, level-specific scripting, final-boss only)

---

## Enemies / Combat

| etype | source file | lumps | tier |
|---|---|---|---|
| `balloonlurker` | levels/misty/balloonlurker.gc | standard enemy lumps | 1 |
| `babak-with-cannon` | levels/misty/babak-with-cannon.gc | standard + cannon target | 2 |
| `darkvine` | levels/jungle/darkvine.gc | standard enemy | 1 |
| `junglefish` | levels/jungle/junglefish.gc | standard enemy | 1 |
| `peeper` | levels/rolling/rolling-lightning-mole.gc | standard enemy | 1 |
| `quicksandlurker` | levels/misty/quicksandlurker.gc | standard enemy | 1 |
| `swamp-rat-nest` | levels/swamp/swamp-rat-nest.gc | `num-lurkers` | 2 |
| `villa-starfish` | levels/village1/village-obs.gc | `num-lurkers` | 2 |
| `sunkenfisha` | levels/sunken/sunken-fish.gc | `count`, `speed`, `distance`, `path-max-offset`, `path-trans-offset` | 2 |
| `sharkey` | engine/common-obs/sharkey.gc | `water-height`, `speed`, `delay`, `distance` | 2 |
| `cave-trap` | levels/robocave/cave-trap.gc | standard | 1 |
| `spider-egg` | levels/robocave/spider-egg.gc | standard | 1 |
| `spider-vent` | levels/robocave/cave-trap.gc | standard | 1 |
| `battlecontroller` | levels/common/battlecontroller.gc | `num-lurkers`, `lurker-type`, `percent`, `pathspawn`, `mode`, `final-pickup`, up to 8 path lumps | 3 |

---

## Platforms / Moving Objects

| etype | source file | lumps | tier |
|---|---|---|---|
| `orbit-plat` | levels/sunken/orbit-plat.gc | `sync` | 2 |
| `square-platform` | levels/sunken/square-platform.gc | `sync`, path | 2 |
| `qbert-plat` | levels/sunken/qbert-plat.gc | `sync`, `index` | 2 |
| `citb-base-plat` | levels/citadel/citb-plat.gc | `sync`, path | 2 |
| `citb-drop-plat` | levels/citadel/citb-drop-plat.gc | `plat-type`, `count`, `sync` | 2 |
| `rigid-body-platform` | engine/common-obs/rigid-body.gc | rigid body params | 3 |
| `ropebridge` | engine/common-obs/ropebridge.gc | `art-name` | 2 |
| `snow-log` | levels/snow/snow-obs.gc | `sync` | 2 |
| `snow-log-button` | levels/snow/snow-obs.gc | `extra-id` | 2 |
| `pontoon` | levels/village2/village2-obs.gc | standard | 1 |
| `tra-pontoon` | levels/training/training-obs.gc | standard | 1 |
| `mis-bone-bridge` | levels/misty/misty-obs.gc | standard | 2 |
| `boatpaddle` | levels/misty/misty-obs.gc | standard | 2 |
| `precurbridge` | levels/jungle/jungle-obs.gc | standard | 2 |
| `accordian` | levels/jungle/jungle-obs.gc | standard | 2 |
| `breakaway-left/mid/right` | levels/misty/misty-obs.gc | standard | 2 |
| `snow-gears` | levels/snow/snow-obs.gc | standard | 1 |
| `snow-bumper` | levels/snow/snow-bumper.gc | `rotmin` | 2 |
| `snow-ball` | levels/snow/snow-ball.gc | path-based | 3 |
| `helix-water` | levels/sunken/helix-water.gc | `water-height` | 2 |
| `slide-control` | levels/sunken/target-tube.gc | level-specific | 3 |
| `swamp-tetherrock` | levels/village2/swamp-blimp.gc | standard | 2 |
| `swampgate` | levels/swamp/swamp-obs.gc | standard | 2 |
| `ceilingflag` | levels/village2/village2-obs.gc | standard | 2 |
| `snow-fort-gate` | levels/snow/snow-obs.gc | standard | 1 |
| `pistons` | levels/village3/village3-obs.gc | standard | 1 |
| `snowpusher` | levels/snow/snow-obs.gc | standard | 1 |
| `jngpusher` | levels/jungle/jungle-obs.gc | standard | 1 |
| `pusher` | levels/rolling/rolling-obs.gc | standard | 1 |

---

## Interactables / Doors / Buttons

| etype | source file | lumps | tier |
|---|---|---|---|
| `eco-door` | engine/common-obs/baseplat.gc | `flags` (eco-door-flags) | 2 |
| `launcherdoor` | levels/common/launcherdoor.gc | `continue-name` | 2 |
| `maindoor` | levels/jungle/jungle-obs.gc | standard | 2 |
| `silodoor` | levels/finalboss/robotboss-misc.gc | standard | 3 |
| `helix-button` | levels/sunken/helix-water.gc | `extra-id` | 2 |
| `helix-slide-door` | levels/sunken/helix-water.gc | `extra-id` | 2 |
| `sun-iris-door` | levels/sunken/sun-iris-door.gc | `proximity`, `trans-offset` | 2 |
| `snow-button` | levels/snow/snow-flutflut-obs.gc | standard | 2 |
| `snow-switch` | levels/snow/snow-obs.gc | standard | 2 |
| `final-door` | levels/finalboss/final-door.gc | final-boss only | 4 |
| `shover` | levels/sunken/shover.gc | `trans-offset`, `collision-mesh-id` | 2 |
| `swingpole` | engine/common-obs/generic-obs-h.gc | standard | 2 |
| `springbox` | levels/jungle/bouncer.gc | `spring-height`, `art-name` | 2 |

---

## Pickups / Eco / Collectables

| etype | source file | lumps | tier |
|---|---|---|---|
| `eco-pill` | engine/common-obs/collectables.gc | `eco-info` | 1 |
| `ecovent` | engine/common-obs/collectables.gc | `eco-info` | 1 |
| `ecoventrock` | levels/beach/beach-obs.gc | standard | 1 |
| `ventblue` | engine/common-obs/collectables.gc | `eco-info` | 1 |
| `ventred` | engine/common-obs/collectables.gc | `eco-info` | 1 |
| `ventyellow` | engine/common-obs/collectables.gc | `eco-info` | 1 |
| `darkecobarrel` | levels/lavatube/lavatube-obs.gc | standard | 2 |
| `crate-darkeco-cluster` | levels/firecanyon/firecanyon-obs.gc | standard | 2 |
| `boat-fuelcell` | levels/misty/misty-obs.gc | level-specific | 3 |
| `water-vol` | engine/common-obs/water-h.gc | `water-height` (full 5-field) | 2 |
| `blue-eco-charger` | levels/sunken/sun-exit-chamber.gc | level-specific | 3 |
| `snow-spatula` | levels/snow/snow-obs.gc | standard pickup | 1 |
| `snow-eggtop` | levels/snow/snow-obs.gc | standard pickup | 1 |
| `cavespatula` | levels/maincave/maincave-obs.gc | standard pickup | 1 |
| `cavespatulatwo` | levels/maincave/maincave-obs.gc | standard pickup | 1 |

---

## Props / Decorations

| etype | source file | lumps | tier |
|---|---|---|---|
| `beach-rock` | levels/beach/beach-rocks.gc | none | 1 |
| `lrocklrg` | levels/beach/beach-rocks.gc | none | 1 |
| `bladeassm` | levels/beach/beach-obs.gc | none | 1 |
| `grottopole` | levels/beach/beach-obs.gc | none | 1 |
| `harvester` | levels/beach/beach-obs.gc | none | 1 |
| `flutflutegg` | levels/beach/beach-obs.gc | none | 1 |
| `hutlamp` | levels/village1/village-obs.gc | none | 1 |
| `mayorgears` | levels/village1/village-obs.gc | none | 1 |
| `revcycleprop` | levels/village1/village-obs.gc | none | 1 |
| `reflector-end` | levels/village1/village-obs.gc | none | 1 |
| `sagesail` | levels/village1/village-obs.gc | none | 1 |
| `windmill-sail` | levels/village1/village-obs.gc | none | 1 |
| `windspinner` | levels/village1/village-obs.gc | none | 1 |
| `village-fish` | levels/village1/village-obs.gc | none | 1 |
| `villa-starfish` | levels/village1/village-obs.gc | `num-lurkers` | 2 |
| `seaweed` | levels/sunken/sunken-obs.gc | none | 1 |
| `spiderwebs` | levels/maincave/spiderwebs.gc | none | 1 |
| `logtrap` | levels/jungle/jungle-obs.gc | none | 1 |
| `lurkerm-piston` | levels/jungle/jungle-obs.gc | none | 1 |
| `lurkerm-short-sail` | levels/jungle/jungle-obs.gc | none | 1 |
| `lurkerm-tall-sail` | levels/jungle/jungle-obs.gc | none | 1 |
| `towertop` | levels/jungle/jungle-obs.gc | none | 1 |
| `seagullflock` | levels/beach/seagull.gc | none | 1 |
| `happy-plant` | levels/rolling/rolling-obs.gc | `max-frame`, `min-frame` | 2 |
| `darkvine` | levels/jungle/darkvine.gc | none | 1 |
| `eggtop` | levels/jungleb/jungleb-obs.gc | none | 1 |
| `scarecrow-a` | levels/training/training-obs.gc | none | 1 |
| `scarecrow-b` | levels/training/training-obs.gc | none | 1 |
| `gondolacables` | levels/village3/village3-obs.gc | none | 1 |
| `snow-spatula` | levels/snow/snow-obs.gc | none | 1 |
| `minecartsteel` | levels/village3/minecart.gc | none | 1 |
| `windturbine` | levels/misty/misty-obs.gc | none | 1 |
| `fishermans-boat` | levels/village1/fishermans-boat.gc | standard | 2 |
| `precursor-arm` | levels/village2/swamp-blimp.gc | none | 2 |
| `periscope` | levels/jungle/jungle-mirrors.gc | `rot-offset` | 2 |
| `reflector-middle` | levels/village1/village-obs.gc | `height-info` | 2 |
| `reflector-mirror` | levels/jungle/jungle-mirrors.gc | `rot-offset`, `alt-vector` | 2 |
| `reflector-origin` | levels/jungle/jungle-mirrors.gc | none | 1 |

---

## NPCs / Story Characters

| etype | source file | lumps | tier |
|---|---|---|---|
| `assistant` | levels/village1/assistant.gc | standard | 2 |
| `assistant-bluehut` | levels/village2/sage-bluehut.gc | standard | 3 |
| `assistant-firecanyon` | levels/firecanyon/assistant-firecanyon.gc | standard | 3 |
| `assistant-lavatube-end` | levels/citadel/assistant-citadel.gc | standard | 3 |
| `assistant-lavatube-start` | levels/lavatube/assistant-lavatube.gc | standard | 3 |
| `assistant-levitator` | levels/village2/assistant-village2.gc | standard | 3 |
| `assistant-villagec` | levels/village3/assistant-village3.gc | standard | 3 |
| `bird-lady` | levels/beach/bird-lady.gc | standard | 2 |
| `bird-lady-beach` | levels/beach/bird-lady-beach.gc | standard | 2 |
| `oracle` | levels/village_common/oracle.gc | `alt-task` | 2 |
| `sage` | levels/village1/sage.gc | standard | 3 |
| `sage-bluehut` | levels/village2/sage-bluehut.gc | standard | 3 |
| `sage-finalboss` | levels/finalboss/sage-finalboss.gc | final-boss only | 4 |
| `sage-villagec` | levels/village3/sage-village3.gc | standard | 3 |
| `minershort` | levels/village3/miners.gc | standard | 2 |
| `minertall` | levels/village3/miners.gc | standard | 2 |
| `evilbro` | levels/intro/evilbro.gc | intro cutscene only | 4 |
| `evilsis` | levels/intro/evilbro.gc | intro cutscene only | 4 |
| `flutflut-bluehut` | levels/village2/flutflut-bluehut.gc | standard | 3 |
| `racer` | levels/racer_common/racer.gc | `index` | 3 |

---

## Level-Specific / Complex Systems

| etype | source file | notes | tier |
|---|---|---|---|
| `keg-conveyor` | levels/misty/misty-conveyor.gc | spline path `path-k`, spawns `keg` children | 3 |
| `mistycannon` | levels/misty/mistycannon.gc | cannon + target system | 3 |
| `junglefish` | levels/jungle/junglefish.gc | `water-height` | 2 |
| `floating-launcher` | levels/sunken/floating-launcher.gc | `spring-height`, `alt-vector` | 2 |
| `sunken-pipegame` | levels/sunken/sunken-pipegame.gc | multi-actor puzzle | 3 |
| `silostep` | levels/misty/misty-warehouse.gc | multi-step | 3 |
| `race-ring` | levels/rolling/rolling-race-ring.gc | race system | 3 |
| `helix-water` | levels/sunken/helix-water.gc | `water-height` | 2 |
| `exit-chamber` | levels/sunken/sun-exit-chamber.gc | level-specific | 3 |
| `lavafall` | levels/lavatube/lavatube-obs.gc | standard | 2 |
| `lavafallsewera` | levels/lavatube/lavatube-obs.gc | standard | 2 |
| `lavafallsewerb` | levels/lavatube/lavatube-obs.gc | standard | 2 |
| `lavabase` | levels/lavatube/lavatube-obs.gc | standard | 1 |
| `lavashortcut` | levels/lavatube/lavatube-obs.gc | standard | 2 |
| `lavayellowtarp` | levels/lavatube/lavatube-obs.gc | standard | 1 |
| `lavaballoon` | levels/lavatube/lavatube-obs.gc | standard | 2 |
| `darkecobarrel` | levels/lavatube/lavatube-obs.gc | standard | 2 |
| `chainmine` | levels/lavatube/lavatube-obs.gc | standard | 2 |
| `energybase` | levels/lavatube/lavatube-energy.gc | energy system | 3 |
| `energydoor` | levels/lavatube/lavatube-energy.gc | energy system | 3 |
| `energyhub` | levels/lavatube/lavatube-energy.gc | energy system | 3 |
| `energylava` | levels/lavatube/lavatube-energy.gc | energy system | 3 |
| `balloon` | levels/firecanyon/firecanyon-obs.gc | standard | 2 |
| `crate-darkeco-cluster` | levels/firecanyon/firecanyon-obs.gc | standard | 2 |
| `caveelevator` | levels/maincave/maincave-obs.gc | standard | 2 |
| `caveflamepots` | levels/maincave/maincave-obs.gc | standard | 1 |
| `cavetrapdoor` | levels/maincave/maincave-obs.gc | standard | 2 |
| `ogre-bridge` | levels/ogre/ogre-obs.gc | standard | 2 |
| `ogre-bridgeend` | levels/ogre/ogre-obs.gc | standard | 2 |
| `ogreboss-village2` | levels/village2/village2-obs.gc | boss variant | 3 |
| `pontoon` | levels/village2/village2-obs.gc | standard | 1 |
| `blue-sagecage` | levels/citadel/citadel-sages.gc | citadel only | 3 |
| `red-sagecage` | levels/citadel/citadel-sages.gc | citadel only | 3 |
| `green-sagecage` | levels/citadel/citadel-sages.gc | citadel only | 3 |
| `yellow-sagecage` | levels/citadel/citadel-sages.gc | citadel only | 3 |
| `citb-arm-section` | levels/citadel/citadel-obs.gc | citadel system | 3 |
| `citb-coil` | levels/citadel/citadel-obs.gc | citadel system | 3 |
| `citb-disc` | levels/citadel/citadel-obs.gc | citadel system | 3 |
| `citb-firehose` | levels/citadel/citb-plat.gc | citadel system | 3 |
| `citb-generator` | levels/citadel/citadel-obs.gc | citadel system | 3 |
| `citb-hose` | levels/citadel/citadel-obs.gc | citadel system | 3 |
| `citb-robotboss` | levels/citadel/citadel-obs.gc | citadel only | 4 |

---

## Quick-Add Candidates (Tier 1 — prop/decoration, just needs art group)

These could all be added to ENTITY_DEFS in a single batch with minimal research:
`beach-rock`, `lrocklrg`, `bladeassm`, `grottopole`, `harvester`, `flutflutegg`,
`hutlamp`, `mayorgears`, `revcycleprop`, `sagesail`, `windmill-sail`, `windspinner`,
`village-fish`, `seaweed`, `spiderwebs`, `logtrap`, `lurkerm-piston`, `lurkerm-short-sail`,
`lurkerm-tall-sail`, `towertop`, `seagullflock`, `eggtop`, `scarecrow-a`, `scarecrow-b`,
`gondolacables`, `minecartsteel`, `windturbine`, `lavabase`, `lavayellowtarp`,
`caveflamepots`, `pontoon`, `tra-pontoon`, `reflector-origin`, `ecoventrock`,
`snow-fort-gate`, `pistons`, `snowpusher`, `jngpusher`, `darkvine`, `peeper`,
`balloonlurker`, `quicksandlurker`, `cave-trap`, `spider-egg`, `eco-pill`,
`ventblue`, `ventred`, `ventyellow`, `ecovent`, `snow-spatula`, `snow-eggtop`,
`cavespatula`, `cavespatulatwo`

---

## Art Group Names — To Verify

Most of the above will need their art group filename confirmed from the source.
Pattern is usually `<etype>-ag.go` but not always (e.g. `floating-launcher` → `floating-launcher-ag.go`).
Run `grep -r "defskelgroup" <file>` to confirm the art group name before adding to ENTITY_DEFS.

---

_Last updated: April 2026. Source: goal_src/jak1/ — all defmethod init-from-entity! declarations._
