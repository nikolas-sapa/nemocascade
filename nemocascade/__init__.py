"""nemocascade — execution-verified cost cascade for Nemotron models on Nebius Token Factory.

Runs a task through a cost-ordered ladder of Nemotron tiers (nano -> super -> ultra).
Each candidate solution is executed in a sandbox (Token Factory Sandboxes on Nebius,
or the local subprocess backend) and only accepted when the verifier passes.
Escalation to a more expensive tier happens only on an execution-verified failure.
"""

__version__ = "0.1.0"
