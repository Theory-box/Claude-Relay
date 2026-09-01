# OpenGOAL Jak 1 — SBK Sound Bank Contents

Extracted directly from `.SBK` binary files using `scratch/parse_sbk.py`.
Last updated: April 2026.

## Summary

- **24 banks** parsed
- **1048 total sounds**
- `common` is always loaded at boot — its sounds are always available
- Level banks (max 2) are loaded per-level via `:sound-banks` in `level-load-info`
- `empty1`, `empty2` are placeholder banks with 1 dummy sound each
- `testtone`, `training` are dev/debug banks

## Key insight for the addon

When filtering sounds by selected bank, always include `common` sounds
since that bank is always loaded. Then add whichever 1-2 level banks are selected.

## beach — 40 sounds

`beach-amb2`, `bird`, `cannon-charge`, `cannon-shot`, `crab-slide`, `dirt-crumble`, `drip`, `egg-crack`, `egg-hit`, `falling-egg`, `fuse`, `gears-rumble`, `grotto-pole-hit`, `lurkercrab-dies`, `lurkerdog-bite`, `lurkerdog-dies`, `lurkerdog-idle`, `monkey`, `pelican-flap`, `pelican-gulp`, `puppy-bark`, `rope-stretch`, `sack-incoming`, `sack-land`, `seagull-takeoff`, `shell-down`, `shell-up`, `snap`, `telescope`, `tower-wind2`, `tower-wind3`, `tower-winds`, `vent-rock-break`, `water-lap`, `worm-bite`, `worm-dies`, `worm-idle`, `worm-rise1`, `worm-sink`, `worm-taunt`

## citadel — 20 sounds

`assembly-moves`, `bridge-piece-dn`, `bridge-piece-up`, `bunny-attack`, `bunny-dies`, `bunny-taunt-1`, `citadel-amb`, `eco-beam`, `eco-torch`, `elev-button`, `mushroom-break`, `robot-arm`, `rotate-plat`, `sagecage-open`, `snow-bunny1`, `snow-bunny2`, `yellow-buzz`, `yellow-explode`, `yellow-fire`, `yellow-fizzle`

## common — 461 sounds *(always loaded)*

`---close-racerin`, `---large-steam-l`, `-lav-dark-eco`, `arena`, `arena-steps`, `arenadoor-close`, `arenadoor-open`, `babak-breathin`, `babak-chest`, `babak-dies`, `babak-roar`, `babak-taunt`, `babk-taunt`, `balloon-dies`, `bigshark-alert`, `bigshark-bite`, `bigshark-idle`, `bigshark-taunt`, `bigswing`, `blob-explode`, `blob-land`, `blue-eco-charg`, `blue-eco-idle`, `blue-eco-jak`, `blue-eco-on`, `blue-eco-start`, `blue-light`, `bluesage-fires`, `boat-start`, `boat-stop`, `bomb-open`, `bonelurk-roar`, `bonelurker-dies`, `bonelurker-grunt`, `breath-in`, `breath-in-loud`, `breath-out`, `breath-out-loud`, `bridge-button`, `bridge-hover`, `bully-bounce`, `bully-dies`, `bully-dizzy`, `bully-idle`, `bully-jump`, `bully-land`, `bully-spin1`, `bully-spin2`, `bumper-button`, `bumper-pwr-dwn`, `burst-out`, `buzzer`, `buzzer-pickup`, `caught-eel`, `cave-spatula`, `cave-top-falls`, `cave-top-lands`, `cave-top-rises`, `cell-prize`, `chamber-land`, `chamber-lift`, `close-orb-cash`, `crab-walk1`, `crab-walk2`, `crab-walk3`, `crate-jump`, `crystal-on`, `cursor-l-r`, `cursor-options`, `cursor-up-down`, `darkeco-pool`, `dcrate-break`, `death-darkeco`, `death-drown`, `death-fall`, `death-melt`, `door-lock`, `door-unlock`, `dril-step`, `eco-beam`, `eco-bg-blue`, `eco-bg-green`, `eco-bg-red`, `eco-bg-yellow`, `eco-engine-1`, `eco-engine-2`, `eco-plat-hover`, `eco3`, `ecohit2`, `ecoroom1`, `electric-loop`, `elev-button`, `elev-land`, `eng-shut-down`, `eng-start-up`, `explosion`, `explosion-2`, `fire-boulder`, `fire-crackle`, `fire-loop`, `fish-spawn`, `flame-pot`, `flop-down`, `flop-hit`, `flop-land`, `flut-land-crwood`, `flut-land-dirt`, `flut-land-grass`, `flut-land-pcmeta`, `flut-land-sand`, `flut-land-snow`, `flut-land-stone`, `flut-land-straw`, `flut-land-swamp`, `flut-land-water`, `flut-land-wood`, `flylurk-dies`, `flylurk-idle`, `flylurk-plane`, `flylurk-roar`, `flylurk-taunt`, `foothit`, `gdl-gen-loop`, `gdl-pulley`, `gdl-shut-down`, `gdl-start-up`, `get-all-orbs`, `get-big-fish`, `get-blue-eco`, `get-burned`, `get-fried`, `get-green-eco`, `get-powered`, `get-red-eco`, `get-shocked`, `get-small-fish`, `get-yellow-eco`, `glowing-gen`, `green-eco-idle`, `green-eco-jak`, `green-fire`, `green-steam`, `greensage-fires`, `grunt`, `hand-grab`, `heart-drone`, `helix-dark-eco`, `hit-back`, `hit-dizzy`, `hit-dummy`, `hit-lurk-metal`, `hit-metal`, `hit-metal-big`, `hit-metal-large`, `hit-metal-small`, `hit-metal-tiny`, `hit-temple`, `hit-up`, `ice-breathin`, `ice-loop`, `icelurk-land`, `icelurk-step`, `icrate-break`, `irisdoor1`, `irisdoor2`, `jak-clap`, `jak-deatha`, `jak-idle1`, `jak-shocked`, `jak-stretch`, `jng-piston-dwn`, `jng-piston-up`, `jngb-eggtop-seq`, `jump`, `jump-double`, `jump-long`, `jump-low`, `jump-lurk-metal`, `jungle-part`, `kermit-loop`, `land-crwood`, `land-dirt`, `land-dpsnow`, `land-dwater`, `land-grass`, `land-hard`, `land-metal`, `land-pcmetal`, `land-sand`, `land-snow`, `land-stone`, `land-straw`, `land-swamp`, `land-water`, `land-wood`, `launch-fire`, `launch-idle`, `launch-start`, `lav-blue-vent`, `lav-dark-boom`, `lav-green-vent`, `lav-mine-boom`, `lav-spin-gen`, `lav-yell-vent`, `lava-mines`, `lava-pulley`, `ldoor-close`, `ldoor-open`, `lev-mach-fires`, `lev-mach-idle`, `lev-mach-start`, `loop-racering`, `lurkerfish-swim`, `maindoor`, `mayor-step-carp`, `mayor-step-wood`, `mayors-gears`, `medium-steam-lp`, `menu-close`, `menu-stats`, `miners-fire`, `misty-steam`, `money-pickup`, `mother-charge`, `mother-fire`, `mother-hit`, `mother-track`, `mud`, `mud-lurk-inhale`, `mushroom-gen`, `mushroom-off`, `ogre-rock`, `ogre-throw`, `ogre-windup`, `oof`, `open-orb-cash`, `oracle-awake`, `oracle-sleep`, `pedals`, `pill-pickup`, `piston-close`, `piston-open`, `plat-light-off`, `plat-light-on`, `pontoonten`, `powercell-idle`, `powercell-out`, `prec-button1`, `prec-button2`, `prec-button3`, `prec-button4`, `prec-button6`, `prec-button7`, `prec-button8`, `prec-on-water`, `punch`, `punch-hit`, `ramboss-charge`, `ramboss-dies`, `ramboss-fire`, `ramboss-hit`, `ramboss-idle`, `ramboss-land`, `ramboss-roar`, `ramboss-shield`, `ramboss-step`, `ramboss-taunt`, `ramboss-track`, `red-eco-idle`, `red-eco-jak`, `red-fireball`, `redsage-fires`, `robber-dies`, `robber-idle`, `robber-roar`, `robber-taunt`, `robo-blue-lp`, `robo-warning`, `robot-arm`, `robotcage-lp`, `robotcage-off`, `rock-hover`, `roll-crwood`, `roll-dirt`, `roll-dpsnow`, `roll-dwater`, `roll-grass`, `roll-pcmetal`, `roll-sand`, `roll-snow`, `roll-stone`, `roll-straw`, `roll-swamp`, `roll-water`, `roll-wood`, `rounddoor`, `run-step-left`, `run-step-right`, `sagecage-gen`, `sagecage-off`, `sages-machine`, `sandworm-dies`, `scrate-break`, `scrate-nobreak`, `select-menu`, `select-option`, `select-option2`, `shark-bite`, `shark-dies`, `shark-idle`, `shark-swim`, `shield-zap`, `shldlurk-breathi`, `shldlurk-chest`, `shldlurk-dies`, `shldlurk-roar`, `shldlurk-taunt`, `shut-down`, `sidedoor`, `silo-button`, `slide-crwood`, `slide-dirt`, `slide-dpsnow`, `slide-dwater`, `slide-grass`, `slide-pcmetal`, `slide-sand`, `slide-snow`, `slide-stone`, `slide-straw`, `slide-swamp`, `slide-water`, `slide-wood`, `slider2001`, `smack-surface`, `small-steam-lp`, `snow-bumper`, `snow-pist-cls2`, `snow-pist-cls3`, `snow-pist-opn2`, `snow-pist-opn3`, `snow-piston-cls`, `snow-piston-opn`, `snow-plat-1`, `snow-plat-2`, `snow-plat-3`, `snw-door`, `snw-eggtop-seq`, `spin`, `spin-hit`, `spin-kick`, `spin-pole`, `split-steps`, `start-options`, `start-up`, `steam-long`, `steam-medium`, `steam-short`, `stopwatch`, `sunk-top-falls`, `sunk-top-lands`, `sunk-top-rises`, `swim-dive`, `swim-down`, `swim-flop`, `swim-idle1`, `swim-idle2`, `swim-jump`, `swim-kick-surf`, `swim-kick-under`, `swim-noseblow`, `swim-stroke`, `swim-surface`, `swim-to-down`, `swim-turn`, `swim-up`, `temp-enemy-die`, `touch-pipes`, `uppercut`, `uppercut-hit`, `v3-bridge`, `v3-cartride`, `v3-minecart`, `vent-switch`, `walk-crwood1`, `walk-crwood2`, `walk-dirt1`, `walk-dirt2`, `walk-dpsnow1`, `walk-dpsnow2`, `walk-dwater1`, `walk-dwater2`, `walk-grass1`, `walk-grass2`, `walk-metal1`, `walk-metal2`, `walk-pcmetal1`, `walk-pcmetal2`, `walk-sand1`, `walk-sand2`, `walk-slide`, `walk-snow1`, `walk-snow2`, `walk-step-left`, `walk-step-right`, `walk-stone1`, `walk-stone2`, `walk-straw1`, `walk-straw2`, `walk-swamp1`, `walk-swamp2`, `walk-water1`, `walk-water2`, `walk-wood1`, `walk-wood2`, `warning`, `warpgate-act`, `warpgate-butt`, `warpgate-loop`, `warpgate-tele`, `water-drop`, `water-explosion`, `water-loop`, `water-off`, `water-on`, `waterfall`, `wcrate-break`, `wood-gears2`, `yel-eco-idle`, `yel-eco-jak`, `yellsage-fire`, `yeti-breathin`, `yeti-dies`, `yeti-roar`, `yeti-taunt`, `zoom-boost`, `zoom-hit-crwood`, `zoom-hit-dirt`, `zoom-hit-grass`, `zoom-hit-lava`, `zoom-hit-metal`, `zoom-hit-sand`, `zoom-hit-stone`, `zoom-hit-water`, `zoom-hit-wood`, `zoom-land-crwood`, `zoom-land-dirt`, `zoom-land-grass`, `zoom-land-lava`, `zoom-land-metal`, `zoom-land-sand`, `zoom-land-stone`, `zoom-land-water`, `zoom-land-wood`, `zoom-teleport`, `zoomer-crash-2`, `zoomer-explode`, `zoomer-jump`, `zoomer-melt`, `zoomer-rev1`, `zoomer-rev2`

## darkcave — 26 sounds

`bab-spid-dies`, `bab-spid-roar`, `button-1b`, `cavelevator`, `cavewind`, `crystal-explode`, `drill-idle`, `drill-idle2`, `drill-no-start`, `drill-start`, `drill-stop`, `drlurker-dies`, `drlurker-roar`, `eggs-hatch`, `eggs-lands`, `lay-eggs`, `mom-spid-dies`, `mom-spid-roar`, `spatula`, `spider-step`, `trapdoor`, `web-tramp`, `yellow-buzz`, `yellow-explode`, `yellow-fire`, `yellow-fizzle`

## empty1 — 1 sounds *(dev/debug)*

`button-1b`

## empty2 — 1 sounds *(dev/debug)*

`button-1a`

## finalboss — 49 sounds

`-bfg-buzz`, `assembly-moves`, `bfg-buzz`, `bfg-fire`, `bfg-fizzle`, `blob-attack`, `blob-dies`, `blob-jump`, `blob-out`, `blob-roar`, `bomb-spin`, `bridge-piece-dn`, `bridge-piece-up`, `charge-loop`, `dark-eco-buzz`, `dark-eco-fire`, `eco-beam`, `eco-torch`, `elev-land`, `explod-bfg`, `explod-bomb`, `explod-eye`, `explosion1`, `explosion2`, `explosion3`, `mushroom-break`, `red-buzz`, `red-explode`, `red-fire`, `robo-hurt`, `robo-servo1`, `robo-servo2`, `robo-servo3`, `robo-servo4`, `robo-servo5`, `robo-servo6`, `robo-servo7`, `robo-servo8`, `robo-servo9`, `robo-taunt`, `robo-yell`, `sagecage-open`, `silo-moves`, `white-eco-beam`, `white-eco-lp`, `yellow-buzz`, `yellow-explode`, `yellow-fire`, `yellow-fizzle`

## firecanyon — 11 sounds

`bubling-lava`, `cool-balloon`, `explod-mine`, `explosion1`, `explosion2`, `lava-amb`, `lava-steam`, `magma-rock`, `zoomer-loop`, `zoomer-start`, `zoomer-stop`

## jungle — 56 sounds

`accordian-pump`, `aphid-dies`, `aphid-roar`, `aphid-spike-in`, `aphid-spike-out`, `aphid-step`, `beam-connect`, `bird`, `bug-step`, `cascade`, `darkvine-down`, `darkvine-move`, `darkvine-snap`, `darkvine-up`, `eco-tower-rise`, `eco-tower-stop`, `elev-land`, `elev-loop`, `fish-miss`, `floating-rings`, `frog-dies`, `frog-idle`, `frog-taunt`, `frogspeak`, `jungle-river`, `jungle-shores`, `logtrap1`, `logtrap2`, `lurk-bug`, `lurkerfish-bite`, `lurkerfish-dies`, `lurkerfish-idle`, `lurkerm-hum`, `lurkerm-squeak`, `mirror-smash`, `monkey`, `pc-bridge`, `plant-chomp`, `plant-eye`, `plant-fall`, `plant-laugh`, `plant-leaf`, `plant-ouch`, `plant-recover`, `plant-roar`, `plat-flip`, `site-moves`, `snake-bite`, `snake-drop`, `snake-idle`, `snake-rattle`, `spider-step`, `steam-release`, `telescope`, `trampoline`, `wind-loop`

## jungleb — 50 sounds

`accordian-pump`, `beam-connect`, `bird`, `bug-step`, `cascade`, `darkvine-down`, `darkvine-move`, `darkvine-snap`, `darkvine-up`, `eco-tower-rise`, `eco-tower-stop`, `elev-land`, `elev-loop`, `floating-rings`, `frog-dies`, `frog-idle`, `frog-taunt`, `frogspeak`, `jungle-river`, `jungle-shores`, `logtrap1`, `logtrap2`, `lurk-bug`, `lurkerfish-bite`, `lurkerfish-dies`, `lurkerfish-idle`, `lurkerm-hum`, `lurkerm-squeak`, `mirror-smash`, `monkey`, `pc-bridge`, `plant-chomp`, `plant-eye`, `plant-fall`, `plant-laugh`, `plant-leaf`, `plant-ouch`, `plant-recover`, `plant-roar`, `plat-flip`, `site-moves`, `snake-bite`, `snake-drop`, `snake-idle`, `snake-rattle`, `spider-step`, `steam-release`, `telescope`, `trampoline`, `wind-loop`

## lavatube — 15 sounds

`ball-explode`, `ball-gen`, `bubling-lava`, `cool-balloon`, `lav-dark-eco`, `lav-mine-chain`, `lava-amb`, `lava-steam`, `yellow-buzz`, `yellow-explode`, `yellow-fire`, `yellow-fizzle`, `zoomer-loop`, `zoomer-start`, `zoomer-stop`

## maincave — 27 sounds

`bab-spid-dies`, `bab-spid-roar`, `button-1b`, `cavelevator`, `cavewind`, `crush-click`, `crystal-explode`, `drill-idle2`, `eggs-hatch`, `eggs-lands`, `gnawer-chew`, `gnawer-crawl`, `gnawer-dies`, `gnawer-taunt`, `hot-flame`, `lay-eggs`, `mom-spid-dies`, `mom-spid-grunt`, `mom-spid-roar`, `spatula`, `spider-step`, `trapdoor`, `web-tramp`, `yellow-buzz`, `yellow-explode`, `yellow-fire`, `yellow-fizzle`

## misty — 41 sounds

`barrel-bounce`, `barrel-roll`, `bone-bigswing`, `bone-die`, `bone-freehead`, `bone-helmet`, `bone-smallswing`, `bone-stepl`, `bone-stepr`, `bonebridge-fall`, `cage-boom`, `cannon-charge`, `cannon-shot`, `falling-bones`, `fuse`, `get-muse`, `keg-conveyor`, `mud-lurk-laugh`, `mud-lurker-idle`, `mud-plat`, `mudlurker-dies`, `muse-taunt-1`, `muse-taunt-2`, `paddle-boat`, `propeller`, `qsl-breathin`, `qsl-fire`, `qsl-popup`, `sack-incoming`, `sack-land`, `teeter-launch`, `teeter-rockland`, `teeter-rockup`, `teeter-wobble`, `telescope`, `trade-muse`, `water-lap`, `water-lap-cl0se`, `zoomer-loop`, `zoomer-start`, `zoomer-stop`

## ogre — 30 sounds

`bridge-appears`, `bridge-breaks`, `dynomite`, `flylurk-plane`, `hit-lurk-metal`, `hits-head`, `lava-loop`, `lava-plat`, `ogre-amb`, `ogre-boulder`, `ogre-dies`, `ogre-explode`, `ogre-fires`, `ogre-grunt1`, `ogre-grunt2`, `ogre-grunt3`, `ogre-roar1`, `ogre-roar2`, `ogre-roar3`, `ogre-walk`, `ogreboss-out`, `rock-hits-metal`, `rock-in-lava`, `rock-roll`, `yellow-buzz`, `yellow-explode`, `yellow-fire`, `yellow-fizzle`, `zoomer-loop`, `zoomer-start`

## robocave — 28 sounds

`bab-spid-dies`, `bab-spid-roar`, `button-1b`, `cavelevator`, `cavewind`, `crush-click`, `drill-hit`, `drill-idle`, `drill-idle2`, `drill-no-start`, `drill-start`, `drill-stop`, `drlurker-dies`, `drlurker-roar`, `eggs-hatch`, `eggs-lands`, `hot-flame`, `lay-eggs`, `mom-spid-dies`, `mom-spid-roar`, `spatula`, `spider-step`, `trapdoor`, `web-tramp`, `yellow-buzz`, `yellow-explode`, `yellow-fire`, `yellow-fizzle`

## rolling — 15 sounds

`close-racering`, `darkvine-grow`, `darkvine-kill`, `darkvine-move`, `get-mole`, `mole-dig`, `mole-taunt-1`, `mole-taunt-2`, `plant-dies`, `plant-move`, `robber-flap`, `roling-amb`, `zoomer-loop`, `zoomer-start`, `zoomer-stop`

## snow — 37 sounds

`--snowball-roll`, `bunny-attack`, `bunny-dies`, `bunny-taunt-1`, `flut-coo`, `flut-death`, `flut-flap`, `flut-hit`, `ice-explode`, `ice-monster1`, `ice-monster2`, `ice-monster3`, `ice-monster4`, `ice-spike-in`, `ice-spike-out`, `ice-stop`, `jak-slide`, `lodge-close`, `lodge-door-mov`, `ramboss-laugh`, `ramboss-yell`, `set-ram`, `slam-crash`, `snow-bunny1`, `snow-bunny2`, `snow-engine`, `snow-spat-long`, `snow-spat-short`, `snowball-land`, `snowball-roll`, `walk-ice1`, `walk-ice2`, `winter-amb`, `yellow-buzz`, `yellow-explode`, `yellow-fire`, `yellow-fizzle`

## sunken — 30 sounds

`--submerge`, `chamber-move`, `dark-plat-rise`, `elev-button`, `elev-land`, `elev-loop`, `large-splash`, `plat-flip`, `puffer-change`, `puffer-wing`, `slide-loop`, `splita-charge`, `splita-dies`, `splita-idle`, `splita-roar`, `splita-spot`, `splita-taunt`, `splitb-breathin`, `splitb-dies`, `splitb-roar`, `splitb-spot`, `splitb-taunt`, `sub-plat-rises`, `sub-plat-sinks`, `submerge`, `sunken-amb`, `sunken-pool`, `surface`, `wall-plat`, `whirlpool`

## swamp — 40 sounds

`bat-celebrate`, `flut-coo`, `flut-death`, `flut-flap`, `flut-hit`, `kermit-dies`, `kermit-letgo`, `kermit-shoot`, `kermit-speak1`, `kermit-speak2`, `kermit-stretch`, `kermit-taunt`, `land-tar`, `lurkbat-bounce`, `lurkbat-dies`, `lurkbat-idle`, `lurkbat-notice`, `lurkbat-wing`, `lurkrat-bounce`, `lurkrat-dies`, `lurkrat-idle`, `lurkrat-notice`, `lurkrat-walk`, `pole-down`, `pole-up`, `rat-celebrate`, `rat-eat`, `rat-gulp`, `rock-break`, `roll-tar`, `rope-snap`, `rope-stretch`, `slide-tar`, `swamp-amb`, `walk-tar1`, `walk-tar2`, `yellow-buzz`, `yellow-explode`, `yellow-fire`, `yellow-fizzle`

## testtone — 2 sounds *(dev/debug)*

`testtone`, `testtone2`

## training — 6 sounds *(dev/debug)*

`break-dummy`, `geyser`, `ocean-bg`, `training-amb`, `village-amb`, `water-lap-cls`

## village1 — 43 sounds

`-fire-crackle`, `-water-lap-cls`, `bird-1`, `bird-2`, `bird-3`, `bird-4`, `bird-house`, `boat-engine`, `boat-splash`, `bubbling-still`, `cage-bird-2`, `cage-bird-4`, `cage-bird-5`, `cricket-single`, `crickets`, `drip-on-wood`, `fire-bubble`, `fly1`, `fly2`, `fly3`, `fly4`, `fly5`, `fly6`, `fly7`, `fly8`, `fountain`, `gear-creak`, `hammer-tap`, `hover-bike-hum`, `ocean-bg`, `seagulls-2`, `snd-`, `temp-enemy-die`, `village-amb`, `water-lap`, `weld`, `welding-loop`, `wind-loop`, `yakow-1`, `yakow-2`, `yakow-grazing`, `yakow-idle`, `yakow-kicked`

## village2 — 12 sounds

`boulder-splash`, `control-panel`, `hits-head`, `rock-roll`, `spark`, `thunder`, `v2ogre-boulder`, `v2ogre-roar1`, `v2ogre-roar2`, `v2ogre-walk`, `village2-amb`, `wind-chimes`

## village3 — 7 sounds

`-bubling-lava`, `cave-wind`, `cool-balloon`, `lava-amb`, `lava-erupt`, `lava-steam`, `sulphur`
