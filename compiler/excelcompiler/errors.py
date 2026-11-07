"""Shared exception types."""


class CompileError(Exception):
    """A problem the user must fix; stops the run with a readable message."""


class PlanError(Exception):
    """A plan that cannot run; the message goes back to the AI for correction."""
