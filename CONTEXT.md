# Foreign Renter Decision World Model

This context describes NestLinker's evidence-backed simulation of the decisions a foreign renter makes before and during a first rental search in Korea. It exists to keep data, product, game, and research language aligned.

## Language

**Foreign Renter Decision World Model**:
A probabilistic decision simulator whose state, actions, transitions, observations, and outcomes represent a foreign renter's Korean housing search.
_Avoid_: Seoul digital twin, physical replica, AI housing oracle

**Decision Rehearsal**:
A bounded simulated journey in which a renter practices choices and receives an evidence-linked debrief before facing the corresponding real situation.
_Avoid_: prediction game, housing recommendation quiz

**Renter Profile**:
The minimum set of circumstances that changes which housing decisions are feasible, such as school or destination, budget, move-in deadline, stay length, language access, and willingness to share.
_Avoid_: persona, demographic stereotype

**Observed State**:
A time-stamped fact admitted through the data repository's provenance, licence, privacy, and quality gates.
_Avoid_: truth, live market

**Modeled State**:
A value estimated from observed state under an explicit method and uncertainty range.
_Avoid_: fact, actual state

**Synthetic Scenario**:
A deliberately generated condition used to exercise decisions when no suitable observation exists; it is never evidence about a real listing or person.
_Avoid_: fake data, predicted listing

**Latent Friction**:
An unobserved obstacle that affects a foreign renter's search, such as language delay, document mismatch, refusal, or inability to inspect remotely.
_Avoid_: foreigner penalty, friendliness score

**Viable Housing Outcome**:
A housing result that meets hard affordability, timing, legal-verification, and commute constraints for the renter profile.
_Avoid_: successful booking, best property

**Avoidable Harm**:
A financial, contractual, safety, timing, or access loss that a reasonable pre-rental check or decision could have reduced.
_Avoid_: bad luck, user error

**Safety-First Objective**:
A lexicographic decision rule that admits only safety-feasible choices, minimizes deposit and contract harm before comparing housing probability, and considers speed or convenience last. A gain in a lower-priority outcome cannot compensate for a safety regression.
_Avoid_: overall risk score, engagement-optimized score

**Safety-Feasible Choice**:
A choice that stays within the renter's declared cash and loss limits, preserves a time- and cost-bounded housing-continuity fallback, and does not skip a mandatory Real-World Checkpoint. When no such choice exists, the valid output is to pause, verify, escalate, or use a bounded temporary fallback.
_Avoid_: guaranteed-safe choice, approved property

**Decision Regret**:
The gap between the outcome of a chosen action and the best feasible action available under the same information and constraints.
_Avoid_: game score, model accuracy

**Evidence Grade**:
The declared basis of an output: `observed`, `modeled`, or `synthetic`, together with its source date and limits.
_Avoid_: confidence score

**Simulation Reliability**:
The degree to which the data coverage, temporal fit, model calibration, and uncertainty support use of a simulation for a stated decision.
_Avoid_: accuracy badge, trust score

**Real-World Checkpoint**:
An official document, licensed professional, direct inspection, or consented real outcome that the simulator cannot replace and must hand the renter to.
_Avoid_: disclaimer link, external verification
