#!/usr/bin/env python3
"""One-shot, explicitly armed whole-host reboot into original-database recovery.

No container/process kill, filesystem cleanup, policy change or forced reboot.
The caller owns the normal recovery locks and invokes only pinned service tools.
"""

from __future__ import annotations

import json
import re
import time
import uuid


class Handoff:
    def __init__(self, q, recovery, backend, opt_in, state):
        self.q, self.r, self.b, self.opt, self.state = q, recovery, backend, opt_in, state
        self.path = state / "reboot-handoff.json"
        self.observation = state / "reboot-observation.json"
        self.record = None
        if self.path.exists() or self.path.is_symlink():
            q.trusted_file(self.path)
            self.record = json.loads(self.path.read_text())
            q.require(
                self.record["enrollment_sha256"] == opt_in["enrollment_sha256"]
                and self.record["cluster_id"] == recovery.e["cluster_id"]
                and self.record["member_id"] == recovery.local["id"]
                and re.fullmatch("[0-9a-f]{32}", self.record["id"]),
                "reboot handoff identity changed",
            )

    def save(self, phase, **extra):
        self.record.update(phase=phase, **extra)
        self.q.atomic_json(self.path, self.record)

    def clean_previous(self, baseline):
        incident = self.r.previous()
        self.q.require(
            not incident or (incident["phase"] == "complete" and incident["ip"] == baseline),
            "unfinished membership/workload recovery forbids reboot",
        )
        staged = self.state / "staged.json"
        if staged.exists() or staged.is_symlink():
            self.q.trusted_file(staged)
            previous = json.loads(staged.read_text())
            self.q.require(
                previous["phase"] == "normal"
                and incident
                and incident["phase"] == "complete"
                and previous["ip"] == baseline
                and previous["member_id"] == self.r.local["id"]
                and previous["cluster_id"] == self.r.e["cluster_id"],
                "unfinished staged lifecycle forbids reboot",
            )
        if self.r.address_journal.exists() or self.r.address_journal.is_symlink():
            self.q.trusted_file(self.r.address_journal)
            previous = json.loads(self.r.address_journal.read_text())
            self.q.require(
                previous["phase"] == "verified"
                and previous["ip"] == baseline
                and previous["member_id"] == self.r.local["id"]
                and previous["cluster_id"] == self.r.e["cluster_id"]
                and previous["node_uid"] == self.r.local["node_uid"],
                "unfinished Node address mutation forbids reboot",
            )

    def before_start(self):
        if not self.record:
            return
        if self.record["phase"] == "complete":
            return
        self.q.require(
            self.record["phase"]
            in ("reboot-dispatch-intent", "reboot-requested", "cold-authorized"),
            "unknown reboot phase",
        )
        boot = self.b.boot_id()
        self.q.require(
            boot != self.record["origin_boot_id"],
            "reboot handoff still on original boot; never retry reboot",
        )
        self.q.require(self.r.local_guard() == self.record["ip"], "address changed across reboot")
        if self.record["phase"] == "cold-authorized":
            self.q.require(
                boot == self.record["recovery_boot_id"], "another reboot interrupted cold recovery"
            )
            self.q.require(
                "staged_id" not in self.record,
                "cold handoff already consumed; preserve staged start outcome",
            )
            self.clean_previous(self.record["old_ip"])
            self.b.quiet()
            return
        self.clean_previous(self.record["old_ip"])
        self.b.quiet()
        self.save("cold-authorized", recovery_boot_id=boot)

    def bind_staged(self, staged):
        if self.record is None or self.record["phase"] == "complete":
            return
        self.q.require(
            self.record is not None
            and self.record["phase"] == "cold-authorized"
            and self.b.boot_id() == self.record["recovery_boot_id"]
            and staged["ip"] == self.record["ip"]
            and staged["member_id"] == self.record["member_id"]
            and staged["cluster_id"] == self.record["cluster_id"]
            and ("staged_id" not in self.record or self.record["staged_id"] == staged["token"]),
            "reboot handoff cannot bind this staged incident",
        )
        self.save(
            "cold-authorized", staged_id=staged["token"], membership_id=staged["membership_id"]
        )

    def linked_stage(self):
        path = self.state / "staged.json"
        self.q.trusted_file(path)
        staged = json.loads(path.read_text())
        self.q.require(
            staged["token"] == self.record.get("staged_id")
            and staged["membership_id"] == self.record["membership_id"]
            and staged["phase"] == "normal"
            and staged["ip"] == self.record["ip"]
            and staged["member_id"] == self.record["member_id"]
            and staged["cluster_id"] == self.record["cluster_id"],
            "linked staged recovery has not reached normal startup",
        )
        incident = self.r.previous()
        self.q.require(
            incident
            and incident["token"] == self.record["membership_id"]
            and incident["ip"] == self.record["ip"],
            "membership incident differs from reboot handoff",
        )

    def watch(self):
        self.b.config()
        boot, ip = self.b.boot_id(), self.b.address()
        incident = self.r.previous()
        baseline = (
            incident["ip"]
            if incident and incident["phase"] == "complete"
            else self.r.e["local_ipv4"]
        )
        if self.record and self.record["phase"] != "complete":
            self.q.require(
                self.record["phase"] == "cold-authorized"
                and boot == self.record["recovery_boot_id"]
                and ip == self.record["ip"],
                "reboot intent remains latched; no repeated request",
            )
            self.linked_stage()
            result = self.r.post_start()
            if self.r.previous()["phase"] == "complete":
                self.save("complete")
            return result
        if ip == baseline:
            return self.r.post_start()
        self.clean_previous(baseline)
        self.q.require(self.r.e.get("armed") is True, "armed enrollment required for reboot")
        network = self.b.running_network(ip, baseline)
        state = self.b.reboot_admission()
        now = time.monotonic()
        observed = {}
        if self.observation.exists() or self.observation.is_symlink():
            self.q.trusted_file(self.observation)
            observed = json.loads(self.observation.read_text())
        expected = {"boot_id": boot, "ip": ip, "old_ip": baseline, "network": network}
        if (
            any(observed.get(key) != value for key, value in expected.items())
            or not 30 <= now - observed.get("monotonic", now) <= 300
        ):
            if (
                any(observed.get(key) != value for key, value in expected.items())
                or not 0 <= now - observed.get("monotonic", now) < 30
            ):
                self.q.atomic_json(self.observation, dict(expected, monotonic=now))
            return "observing-running-address"
        self.b.stable_address(ip)
        self.q.require(
            self.b.running_network(ip, baseline) == network
            and self.b.boot_id() == boot
            and self.b.reboot_admission() == state,
            "host changed during reboot proof",
        )
        if self.record:
            self.q.require(
                self.record["phase"] == "complete" and self.record["origin_boot_id"] != boot,
                "one reboot request per original boot; no loop",
            )
            archive = self.state / ("reboot-archive-" + self.record["id"] + ".json")
            if archive.exists() or archive.is_symlink():
                self.q.trusted_file(archive)
                self.q.require(
                    json.loads(archive.read_text()) == self.record, "reboot archive conflicts"
                )
            else:
                self.q.atomic_json(archive, self.record)
        self.record = dict(
            id=uuid.uuid4().hex,
            member_id=self.r.local["id"],
            cluster_id=self.r.e["cluster_id"],
            enrollment_sha256=self.opt["enrollment_sha256"],
            origin_boot_id=boot,
            ip=ip,
            old_ip=baseline,
            service=state,
            network=network,
        )
        self.save("reboot-dispatch-intent")
        # Return code only acknowledges the asynchronous request. On any timeout,
        # interruption, or error the prior intent remains; do not retry or force.
        self.b.request_reboot()
        self.save("reboot-requested")
        return "reboot-request-accepted; cold recovery not yet verified"
