# String Engine — Philosophy & Direction

Written 2026-07-22, after a long design conversation. Purpose: give a future session
enough context to pick up the *thinking*, not just the code. Read alongside
`session-notes/2026-07-22-string-engine.md` (which covers the engine architecture and
every bug fixed to date).

---

## 1. The project, one paragraph

A browser-based topology-first physics / artificial-life engine. Strings made of nodes
and edges, with bonding, breaking, growth, and collision. The long-term goal is not a
pretty simulation — it is **emergent self-replication**: conditions rich enough that
replicators arise, rather than replicators that were authored. The builder's stance is
"gardener, not engineer": design the environment, hunt for the organisms.

---

## 2. The end goal: a replicator cell

The target design (user's own sketch, held loosely):

- A **sphere with a hole**. Small building blocks pass in; larger shapes inside can't get out.
- Blocks **merge into longer strings** inside the cell.
- Strings take on the shape of **seed shapes** already inside — and crucially, the seed
  is not an authored template but a **bend**: a buckle arising from natural forces.
  Magnetism does double duty — it *causes* the buckled shape, and it *attracts* strings
  to lay against it.
- Strings **harden** into that shape, becoming replicates of the bend.
- Hardened strings can no longer leave, so the cell fills. Pressure/strain builds until
  the **wall bursts**, releasing copies.

**Self-imposed constraint:** the sphere-with-a-hole and the seed shapes must be able to
*arise naturally*, even if hand-placed the first time. Candidate simplification: the
sphere **is** the seed shape.

**Quality bar the user set:** a replicator that makes a random shape for no reason is
**boring**. For it to count, the copied shape must feed back — be a component in building
the replicator cell, or another kind of cell, or something more complex. Copy and copier
should go hand in hand.

**Build ladder:** sim polish → custom shapes with interesting dynamics (simple motors,
cells with tendrils for movement) → a simple self-organizing cell with a **mouth hole and
an out hole** and self-organizing internals that carry things through → the replication cell.

---

## 3. The philosophical thread: are physics-engine failures bugs or features?

This is the spine of the conversation. Summary of where it landed.

### 3.1 Bug vs feature is about intent, not about the world

"Bug" is a fact about the designer's intentions. Physics is what it does, not what it was
meant to do. An inhabitant of a flawed simulation isn't missing information about
*mechanism* — they could in principle find the exact cause — they're missing information
about *purpose*, and purpose isn't a physical property. From inside, there are no glitches.
There are only laws.

Our own physics already has this texture. QFT blows up at zero separation; renormalization
was treated as an embarrassment for decades (Dirac never accepted it) and turned out to be
a deeper statement about short-distance physics. That is *exactly* "two objects overlap and
explode."

### 3.2 Detection from inside: conceded, mostly

Claude initially argued there's a fingerprint: substrate leaks depend on quantities with
no in-world meaning (object count, processing order, memory layout), and no mediating
mechanism could carry them.

**The user's counter won.** A leak can wear in-world clothing — if collisions resolve
differently in dense regions, inhabitants write a *density term* into the law and never
flinch. Density is a real quantity in their world. And the stronger version — quantum
tunneling *itself* being a baked-in leak, with everything downstream built to make it look
lawful — can't be closed at all. Underdetermination is real; any anomaly can be absorbed
by positing a field.

### 3.3 What survives detection: cost, not possibility

You can always save the appearances, but **not cheaply**. A field invented to absorb
load-dependent rounding needs no propagation delay, no falloff, no conserved quantity, no
localizable source, and coupling that changes with object count — each a new posit doing no
other work. Maxwell's field *paid* (predicted radio, unified light and electricity). A
rescue-field never pays.

So the in-world criterion is **unification vs accumulation**: does the count of independent
principles shrink as you learn more, or grow? That's answerable from inside and isn't
interpretive. (Uncomfortably, we're partway along that spectrum ourselves — ~19 undetermined
Standard Model parameters, dark energy fitted to one observation.)

### 3.4 The reframe that actually matters

The user kept saying "we won't have conscious entities, so this is all just philosophy."
**That's backwards.** Swap the question:

> Not *"could an inhabitant detect this glitch?"* — needs an observer, unanswerable.
> But *"could a lineage come to depend on it?"* — needs nothing but selection.

Concrete: cells burst from internal pressure; tunneling lets bodies slip through walls when
things get tight; lineages that leak a little survive longer, lineages with perfect seals pop
early; wall properties drift toward the regime where tunneling happens at a useful rate.
**That is depending on it.** The glitch is now load-bearing, with nothing aware of anything.

This kills the relativist move. "Physics failures can be interpreted any way you want" is
**false**. If lineages are built around an artifact, it is load-bearing *whether or not you
call it one*. Interpretation, no. **Measurement, yes.**

### 3.5 The real criterion: stationarity, not accuracy, not locality

Successive corrections, in order:

- Not **in-world vs substrate** — leaks can dress as in-world quantities.
- Not **local vs distant** — tides are action at a distance and life evolved around them.
  What made tides usable is that the moon's orbit is *stable*.
- Not **predictable vs random** — radioactive decay is irreducibly random per event and
  rock-solid in aggregate; evolution *runs on* that randomness (mutation).
- Not **uniform slowdown** — if everything slows equally that's a clock rescaling, invisible
  from inside (user's correction; Claude was sloppy).

What's left: **stationarity**. Evolution doesn't need locality, determinism, or
predictability. It needs the *statistics to hold still* long enough for a lineage to track
them.

- Unpredictable-but-stationary → fertile. This is the noise evolution feeds on.
- Statistics that themselves drift, for reasons outside the world → unusable.

The asymmetry that makes this stick: a billion-year civilization can absorb any regularity
however baroque, because it can **re-derive**. Selection cannot. It has no memory and no
theory — if the leak rate shifts because something spawned across the map, the lineage tuned
to the old rate is *already dead*. **Explicable to an observer ≠ usable by evolution.**

### 3.6 Measured as a ratio, not a duration

"Fast" and "slow" need no external clock. The measure is **drift rate ÷ generation rate** —
dimensionless, internal to the sim. A bacterium reproducing every 20 minutes has 250,000
generations to track a decade of drift. Same seconds, different meaning.

So: does the artifact hold still for enough reproductive cycles that a lineage can track it?

### 3.7 Two caveats conceded to the user

- **Robustness.** Life doesn't merely track statistics, it *buffers* them — homeostasis,
  dormancy, spores, generalists. Environmental variability actively *selects for* robustness
  (bet-hedging). So drift isn't purely lethal; it can shape. Claude overstated fragility.
- **Scale.** We can't rule out complexity at scales/timescales we never observe (the user's
  "a universe inside the collision"). Effective field theory is why this is respectable and
  also why it can't be settled from here: short-distance structure *decouples*. (The specific
  collider example doesn't work — quark-gluon plasma thermalizes rather than organizing —
  but the general point stands.)
- **Additional criterion this implies:** stationary **and slow enough to accumulate**.
  Complexity needs the previous layer still standing when the next arrives. A billion
  beautiful structures that die in a millisecond build nothing. *This is a live risk in the
  sim itself*, not just a philosophical note.

### 3.8 The punchline

**The metaphysics was never load-bearing. The stationarity was.** Whether stability comes
from real laws or a well-behaved substrate makes no difference to what evolves. Only the
stability itself matters. Our reality passed this test empirically — four billion years of
unbroken lineage *is* a measurement of stationarity, whatever is true underneath.

---

## 4. Engineering consequences (the part that changes what we build)

This is the payoff. The philosophy converts into concrete rules:

1. **Don't chase maximum accuracy as such.** A perfectly accurate sim has no tunneling, no
   explosive overlap, no chaos injection — you'd optimize away your own raw material. Also
   don't chase sloppiness. The bad axis isn't accurate/sloppy, it's **consistent/inconsistent**.
2. **Chase determinism and load-independence.** Fixed timestep. Fixed iteration count. No
   quality scaling with object count. Then whatever failures remain are *the same failures
   every time* — the kind a lineage can grip. Conveniently, this is cheap; no million-year run.
3. **Non-uniform substrate effects are the enemy.** Uniform slowdown: harmless. But a busy
   region getting fewer collision iterations than an empty one means the same in-world
   situation resolves differently depending on machine load. That is the one thing selection
   cannot build on.
4. **Tunneling should be emergent, not a rule.** The user rejected speed-keyed tunneling
   himself mid-sentence ("that's applying a hard rule"), and rejected frame-skipping because
   jitter. Target: tunneling that falls out of deterministic in-world state — geometry,
   speed, shape. The **shape-selective** version he sketched is the good one (see §5).
5. **Watch the accumulation timescale.** If interesting structure forms and dies faster than
   anything can build on it, the sim is generating beauty and no complexity.

### Tension worth resolving later: porousness slider vs emergent tunneling

The user wants **pass-through walls** (explicitly *not* cheating — the sim is 2.5D, so a hole
seen top-down is a legitimate hole that 2D topology can't otherwise express). But he also
insists tunneling must be emergent, not authored.

**Proposed synthesis (not yet agreed):** keep them as two different things.
- **Porousness / pass-through = a designed material property.** It's an in-world quantity,
  deterministic and stationary, so it's perfectly legitimate — it's a *hole*, not a glitch.
- **Tunneling = the emergent, rare failure.** Left to arise from the physics.

Conflating them is what makes the porousness slider feel like cheating.

---

## 5. Feature backlog implied by the goal

- **Pass-through walls** (2.5D "hole" justification). See tension above.
- **Hardening over time** — but not a one-off flag. Implies a **life cycle**: assign a
  lifetime, then drive any or all properties along a **curve over that lifetime**.
- **Death & decay** — materials break down, building blocks return to the pool to rebuild
  basic things. The lifecycle drags you here inevitably.
- **Pressure.** Real pressure (high outside → low inside) isn't reachable with magnetic-style
  forces alone; it needs thousands of particle-strings acting as air. Works, but slow. Open
  problem: a cheaper pressure model.
- **Six base string types** with distinct properties that can all merge into a line — e.g.
  large yellow circles, thin red lines, blue that wants to curl, magenta curling opposite and
  thicker-than-wide. Chains emerge unpredictably from bonding rules. The interesting bet:
  certain *combinations* (large-yellow → red → large-yellow) create physics interactions that
  are hard to handle — spiky blue bodies catching in creases and being forced through the wide
  red line. That's a **shape-selective tunneling system**, and it's more grounded than either
  authoring tunneling or forbidding intersection outright.
- **Auto-decimation toward equidistant points** with a near-fixed world scale, everything
  dynamically subdividing to fit (user floated this as the eventual fix for the
  compression/spacing family of problems).

---

## 6. Open tensions (deliberately unresolved)

- **Discovery vs planning.** The user argued both and settled neither. He leans discovery
  ("environment whose rules cause unplanned replicators to emerge") but also stated the
  planning path ("design a stable replicator, then find the blocks/forces/rules that make it
  emerge"). Suggested framing, not yet adopted: **plan the environment, discover the organisms.**
- **Porousness as authored affordance vs tunneling as emergent failure** (§4).
- **Pressure realism vs compute budget** (§5).

---

## 7. Known outstanding issue in the engine

Some connectable strings still render compressed/small — the "every other string in a
bonding stream is squished" pattern. User suspects the connecting force is shrinking them.
Not root-caused; user has declared it low priority ("looks fine, behaves fine, just
annoying"). Candidates not yet checked: merge blend, holding-bond rest length, or bond force
interacting with negative grow.

Also still on the shelf: the **per-frame safety cap** (bound bond/break events or coalesce
topology rebuilds per frame) so heavy churn degrades to "a bit laggy" rather than a freeze.
Note this is *also* a stationarity concern — a cap that kicks in based on load is exactly the
kind of load-dependent behavior §4.3 warns about. Prefer a deterministic bound.

---

## 8. How the user works (for whoever picks this up)

- Values simple rules → emergent complexity. Every feature should be a zeroable slider/toggle.
- Wants to *see* progress; quality-first; prefers physical/emergent solutions over arbitrary
  band-aids (rejected a cooldown timer in favor of repulsion, and was right to).
- Wants more control even at the cost of denser UI — "we'll reorganize UI later."
- Uses text-to-speech; messages have transcription artifacts. Interpret charitably.
- **Prefers short chunked replies in conversation** — one point per message, interactive
  back-and-forth, not walls of text. ADD; long blocks are hard to read.
- Wants to be told *before* long-standing "beloved bug" behavior gets fixed.
- Push big files to the repo, keep chat lean.
