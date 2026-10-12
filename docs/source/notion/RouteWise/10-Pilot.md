# Real-delivery pilot measurement

[Home](../RouteWise.md)

**Status:** planned. No pilot or claimed savings exist.

Use a small owner-approved delivery round after Phase 5 technical tests. Choose consenting riders, a known service area and comparable baseline rounds. Record weather, order count, stops, riders, endpoints and unusual interruptions so differences can be interpreted.

| Measure | Collection method | Interpretation |
|---|---|---|
| Admin planning time | Manual stopwatch from validated upload to usable plan | Compare with the startup's existing planning workflow |
| Actual distance | Consistent rider odometer/manual record | Report km per round and per completed order |
| Actual round duration | Manual start/finish times and interruptions | Separate delivery service time from travel where practical |
| Completion count | Existing order statuses and manual reconciliation | Report completed, postponed and pending counts |
| Customer unavailable events | Manual tally | Assess usefulness of the quick-call workflow |
| Reroute latency and usefulness | Test log and short rider note | Include failed requests and connectivity conditions |
| Offline update integrity | Queue/acknowledgment reconciliation | Count lost, duplicated or conflicting accepted updates |
| Usability | Rider/admin observations | Identify confusing screens or excessive taps |

These are pilot observations, not new fuel analytics or an in-app reporting feature. Keep real customer details out of Notion. Use pseudonymous round/rider IDs and aggregate results.

Before the pilot, set an agreed baseline and success thresholds using actual operational data. Stop for wrong destinations, unauthorized data exposure or status loss. Record corrective work and retest. A release requires human approval, deployment evidence, backups and rollback readiness.
