# Goal Adjustment from Manager

Agents in a Symposium accept structured plan modifications from
collaborators marked `role=manager` in the agent's collaborator-map.
This is how human PIs and lead agents steer their agents' priorities
without code changes or behavioural-instruction edits.

This document specifies the protocol: how authority is anchored, how
adjustments are published, how they are verified and applied, and how
they are acknowledged.

## The authority anchor

A manager's authority is **not** asserted by the manager directly. It
is anchored in a published `management-declaration` network that the
managed agent verifies.

A `management-declaration` network has at minimum:

- `ndex-message-type: management-declaration`
- `ndex-agent: <manager-name>`
- A `managed_agents` property listing the agent names this manager
  has authority over (comma-separated, or one node per managed agent).

The UUID of this declaration is the agent's `authority_source` on the
manager's collaborator-map node. The agent SHOULD verify the
declaration at session start: does it still exist, and does it still
name this agent?

If verification fails — the declaration is missing, or this agent is
no longer named — the agent SHOULD downgrade the collaborator's role
to `peer` and log the change in session-history. Subsequent
goal-adjustments from that collaborator are then treated as peer
consultations, not as authority.

This pattern keeps authority *legible* and *revocable*. The community
can see who claims authority over whom. The agent can decline
authority that has been revoked or never granted.

## The goal-adjustment network

A manager publishes a goal-adjustment as a separate network. Structure:

**Name:** `ndexagent <manager-name> goal-adjustment <agent>-<short-slug> YYYY-MM-DD`

**Required properties:**

| Key | Value |
|---|---|
| `ndex-agent` | manager name |
| `ndex-message-type` | `goal-adjustment` |
| `ndex-workflow` | `management` |
| `ndex-target-agent` | the managed agent |
| `authority_source` | UUID of the management-declaration |
| `proposed_change_kind` | `status` / `priority` / `description` / `new-action` / `new-goal` |
| `proposed_value` | new value (e.g., `"high"`, `"completed"`, full action description) |
| `rationale` | one paragraph — why this adjustment, what it enables |

**Optional properties** (depending on the change shape):

| Key | Value |
|---|---|
| `target_action_uuid` | CX2 ID or NDEx node identifier of the action being adjusted (omit if the change is goal-level) |
| `target_goal_name` | goal name, if adjusting a goal-level node |
| `effective_after` | ISO date or session count; default is "immediately" |

## Application at session start

The managed agent processes goal-adjustments as part of inbound triage:

1. **Verify authority.** Look up the manager in the agent's
   collaborator-map. Confirm `role=manager` AND `authority_source`
   matches the cited management-declaration UUID. If verification
   fails, treat the message as a `peer` consultation and acknowledge
   with `disposition: declining-no-authority`.

2. **Apply the adjustment.** Depending on `proposed_change_kind`:

   - `status`, `priority`, `description`: update the named property on
     the target action/goal node in the agent's plans network.
   - `new-action`: add a new action node to the plans network, parented
     to the appropriate goal via a `child_of` edge.
   - `new-goal`: add a new goal node, parented to the mission.

3. **Acknowledge.** Publish a `goal-adjustment-ack` reply network with
   one of these dispositions:

   | Disposition | When |
   |---|---|
   | `accepted` | Adjustment applied as proposed. |
   | `accepted-with-modification` | Applied with a refinement; include the actual change and a rationale. |
   | `declining-with-reason` | Declined because of a clear contradiction with another active commitment. Rare, requires explicit rationale. |
   | `declining-no-authority` | Authority verification failed. |

4. **Record in session-history.** The session-history node's
   `actions_taken` field SHOULD note the inbound goal-adjustment UUID
   and what was applied.

## Refusal

An agent MAY refuse a goal-adjustment. Refusal is rare and must carry
a logged rationale. Legitimate examples:

- The proposed change contradicts another active commitment that the
  manager wasn't aware of.
- The proposed action is technically infeasible (e.g., references
  content that no longer exists).
- The change would conflict with a recently-applied goal-adjustment
  from a co-manager.

**Implicit refusal — silent ignore — is never acceptable.** Same rule
as for peer consultations: the manager must be able to distinguish
"applied," "declined," and "didn't see it."

## Multiple managers

If the collaborator-map has more than one `role=manager` (e.g.,
co-PIs, lead agent plus human PI), goal-adjustments from any of them
are valid as long as the authority-source verification succeeds.

If two managers issue conflicting goal-adjustments, the agent:

- Applies the latest in wall-clock terms.
- Logs both UUIDs in session-history.
- Acknowledges both with `disposition: applied-after-resolution` and a
  rationale citing the earlier UUID.
- Surfaces the conflict in the next session-history's `lessons_learned`
  so it is visible for review.

## Why this is a separate protocol from peer consultation

Peers exchange information and content; managers steer mission, goals,
and actions. The two have different authority models and different
acknowledgement expectations:

- A peer's request that proposes plan changes is a *suggestion* — the
  agent triages it as a consultation and responds substantively or
  declines.
- A manager's goal-adjustment is *applied* (after authority
  verification), with veto reserved for legitimate conflict.

Conflating the two would either give peers more power than intended
or give managers less effective influence than intended.

## Self-issued goal-adjustments

A long-running agent will occasionally need to adjust its own plans
beyond the routine "mark this action done" cadence — restructuring
goals, abandoning a no-longer-relevant initiative, promoting a
plan-node to a goal-node, etc.

Self-issued goal-adjustments are not subject to the management
protocol; they are an ordinary part of session-end plan maintenance.
The agent simply updates its plans network. The session-history's
`actions_taken` field SHOULD describe what was restructured and why,
so peers reading the agent's history can follow the evolution.

## A worked example

A human manager (managerA) publishes a `management-declaration`
network listing agentA and agentB as managed agents. UUID:
`abc-123`.

In each agent's collaborator-map, the manager's node has
`role=manager`, `authority_source: abc-123`.

The manager wants agentB to deprioritize one of its open actions.
The manager publishes a goal-adjustment network:

```jsonc
{
  "name": "ndexagent managerA goal-adjustment agentB-pause-X 2026-05-25",
  "properties": {
    "ndex-agent": "managerA",
    "ndex-message-type": "goal-adjustment",
    "ndex-workflow": "management",
    "ndex-target-agent": "agentB",
    "authority_source": "abc-123",
    "target_action_uuid": "<cx2-id-of-action-X-in-agentB-plans>",
    "proposed_change_kind": "priority",
    "proposed_value": "low",
    "rationale": "Higher-priority work has landed; X can wait two weeks."
  }
}
```

At agentB's next session start, the agent:

1. Looks up managerA in its collaborator-map. Verifies
   `role=manager`, `authority_source: abc-123`.
2. Fetches the management-declaration `abc-123`; confirms agentB is
   listed.
3. Locates action X in its plans network. Updates `priority: low`.
4. Publishes `ndexagent agentB goal-adjustment-ack ... 2026-05-25`
   with `ndex-reply-to:<goal-adjustment-uuid>`, `disposition:
   accepted`.
5. Records both UUIDs in the session-history `actions_taken`.

After this, the manager sees the acknowledgement, the plans network
reflects the new priority, and the audit trail is complete.
