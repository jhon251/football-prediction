"""DATA-004: prospective lineup capture pipeline package.

Captures starting-XI information BEFORE kickoff from live sources, storing
immutable time-stamped snapshots so that every record can PROVE when the
information was available to the system (information_available_time < kickoff
=> time_safe=True).

Time model (three clocks, all UTC-aware):
  source_event_time      native publication time from the source (ESPN: None)
  capture_time           when THIS system observed the state (poll time)
  information_available_time = source_event_time if present else capture_time
  time_safe              information_available_time < kickoff_utc (STRICT)

If the source has no native published_at, time_trust='capture_proxy' and the
record is time_safe only via our own immutable capture evidence - capture
time is NEVER presented as the source's publication time.
"""
