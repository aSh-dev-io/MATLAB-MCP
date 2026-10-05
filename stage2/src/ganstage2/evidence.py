"""Evidence classification for every quantity Stage 2 produces.

The governing rule of this project is that a simulated number and a measured
number must never be presented as the same kind of thing. Stage 1 output is a
*Digital-Twin simulation*, so anything derived from it inherits that status no
matter how physical the equation looks.

Every column added in 2B/2C/2D therefore carries an :class:`EvidenceClass`, and
the dashboard prints that class next to the value. The ordering of the enum is
deliberate, strongest evidence first, so that ``max()`` over a set of classes
reports the weakest link in a chain.
"""

from __future__ import annotations

from enum import Enum


class EvidenceClass(str, Enum):
    """How well supported a quantity is, from strongest to weakest.

    The ordering is by evidential strength. A chain of reasoning is only as
    strong as its weakest input, so callers aggregate with ``max()``.
    """

    #: Reproduced against a printed, measured datasheet value at the datasheet's
    #: own test condition. The *anchor* is measured; the model agreeing with it
    #: is a calculated comparison, not a measurement of the device under test.
    VALIDATED_AGAINST_DATASHEET = "VALIDATED_AGAINST_DATASHEET"

    #: A value printed in the source dataset. Someone measured this on a real
    #: device; we are only reading it.
    DATASET_DERIVED = "DATASET_DERIVED"

    #: Arithmetic or algebra on simulated/dataset inputs. No new physics, no new
    #: assumption. Exactly reproducible.
    CALCULATED = "CALCULATED"

    #: A physics relation applied beyond the regime where it is directly
    #: observed, so it carries explicit modelling assumptions.
    PHYSICS_MODELLED = "PHYSICS_MODELLED"

    #: Purely a property of the Digital Twin. Not a statement about any device.
    SIMULATED = "SIMULATED"

    #: An analysis convention chosen by this pipeline, not by physics.
    CONVENTION = "CONVENTION"

    #: Not derivable from the available evidence. Always carries a reason.
    UNAVAILABLE = "UNAVAILABLE"

    @property
    def rank(self) -> int:
        """0 for the strongest class, increasing as evidence weakens."""
        order = list(EvidenceClass)
        return order.index(self)

    @property
    def is_quantitative(self) -> bool:
        """Whether a number may legitimately be attached to this class."""
        return self is not EvidenceClass.UNAVAILABLE


#: Human-readable description used in reports and the dashboard.
EVIDENCE_DESCRIPTIONS: dict[EvidenceClass, str] = {
    EvidenceClass.VALIDATED_AGAINST_DATASHEET: (
        "compared against a measured datasheet value at the datasheet test condition"
    ),
    EvidenceClass.DATASET_DERIVED: (
        "printed in the source dataset; measured on a real device, only read here"
    ),
    EvidenceClass.CALCULATED: (
        "arithmetic on the above with no added physics or assumption"
    ),
    EvidenceClass.PHYSICS_MODELLED: (
        "physics relation applied beyond its directly observed regime; carries "
        "explicit assumptions"
    ),
    EvidenceClass.SIMULATED: (
        "output of the Stage 1 Digital Twin; a property of the model, not of any device"
    ),
    EvidenceClass.CONVENTION: (
        "analysis convention chosen by this pipeline, not a physical constant"
    ),
    EvidenceClass.UNAVAILABLE: (
        "not derivable from the available evidence; no value is asserted"
    ),
}

#: Classes that may be presented as a measured property of a real device.
#: Nothing in this Stage 2 pipeline reaches this set, and that is the point.
MEASURED_CLASSES: frozenset[EvidenceClass] = frozenset()


def weakest(*classes: EvidenceClass) -> EvidenceClass:
    """Aggregate evidence classes, returning the weakest link in the chain."""
    real = [c for c in classes if c is not None]
    if not real:
        return EvidenceClass.UNAVAILABLE
    return max(real, key=lambda c: c.rank)


def describe(cls: EvidenceClass) -> str:
    """One-line human-readable meaning of an evidence class."""
    return EVIDENCE_DESCRIPTIONS[cls]
