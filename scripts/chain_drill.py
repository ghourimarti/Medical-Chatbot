#!/usr/bin/env python
"""Failover drill (D4b): break each leg in turn and prove the NEXT one takes over.

WHY A DRILL AND NOT A UNIT TEST
-------------------------------
The unit tests prove the chain OBJECT fails over. They cannot prove that YOUR chain, with
YOUR keys, against the real Groq and OpenAI endpoints, degrades in the order you
configured. A fallback that has never been exercised is not a fallback, it is an
assumption - and the first time it runs will be during an outage.

HOW IT BREAKS A LEG
-------------------
By blackholing the leg's HOSTNAME in the API container's /etc/hosts - not by stopping
containers, not by editing .env:

  * `docker stop sglang` costs ~5 minutes to come back (weight load + CUDA graph capture),
    so a stop/start drill takes 20 minutes and nobody runs it twice.
  * Editing .env needs an API restart, which resets every counter you are watching and
    changes the thing you are measuring.
  * A hosted venue cannot be stopped at all. Groq is somebody else's computer.

Pointing a host at 127.0.0.1 makes connections fail immediately - the same ProviderError a
real outage produces, arriving fast enough to keep the drill short. One file copy reverts
it, and nothing outside the container is touched.

WHAT IT CANNOT PROVE
--------------------
A DNS blackhole is a CONNECT failure. It does not reproduce a provider that accepts the
connection then returns 500s, hangs past the timeout, or streams half an answer and dies.
Mid-stream failure is explicitly NOT covered: FailoverModel.stream refuses to fail over
once tokens are on the wire (the STREAMING RULE), and this drill uses the non-streaming
path. A pass means "the chain is wired correctly", not "every failure mode is handled".
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "http://localhost:5007"
CTR = "p5-medical-chatbot-api-1"
REDIS = "p5-medical-chatbot-redis-1"
BAK = "/tmp/hosts.medbot.bak"

# httpx keeps idle connections in a pool, default keepalive_expiry = 5.0s, and DNS is
# consulted ONLY when a new connection is opened. So a blackhole applied while a warm
# connection is still pooled changes nothing: the request rides the old socket straight
# past /etc/hosts. The first version of this drill did exactly that and reported the
# primary answering with the primary "down" - a false PASS in the making, and the reason
# this constant exists rather than a bare sleep(1).
POOL_DRAIN_SECONDS = 8.0

LEG_HOST = {
    "local-sglang": "sglang",
    "local-vllm": "vllm",
    "groq": "api.groq.com",
    "openai": "api.openai.com",
}

# Distinct IN-CORPUS questions, one per step.
#   distinct  - an exact-match response cache would otherwise answer from Redis without
#               touching a venue, and the drill would "pass" having proved nothing.
#   in-corpus - a retrieval-gate no_answer never calls the model, so it reports no venue.
QUESTIONS = [
    "What is emphysema?",
    "What are the symptoms of pneumonia?",
    "What causes cirrhosis of the liver?",
    "How is asthma treated?",
    "What is chickenpox?",
]


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def hosts_snapshot():
    sh("docker", "exec", "-u", "root", CTR, "sh", "-c", "test -f " + BAK + " || cp /etc/hosts " + BAK)


def blackhole(legs):
    """Reset /etc/hosts, then point each named leg's hostname at 127.0.0.1."""
    sh("docker", "exec", "-u", "root", CTR, "sh", "-c", "cp " + BAK + " /etc/hosts")
    for leg in legs:
        entry = "127.0.0.1 " + LEG_HOST[leg]
        sh("docker", "exec", "-u", "root", CTR, "sh", "-c", "echo " + entry + " >> /etc/hosts")


def verify_blocked(legs):
    """Confirm from INSIDE the container that each broken leg is now unreachable.

    Verifying the injection is not paranoia: a drill whose failure injection silently does
    nothing reports PASS for a chain that was never tested, which is worse than no drill.
    This opens a NEW connection, so it proves DNS - the pool drain above is what makes the
    APPLICATION follow suit.
    """
    for leg in legs:
        host = LEG_HOST[leg]
        r = sh("docker", "exec", CTR, "python", "-c",
               "import socket;print(socket.gethostbyname(" + repr(host) + "))")
        if r.stdout.strip() != "127.0.0.1":
            print("         WARNING: " + host + " resolves to " + r.stdout.strip()
                  + " - blackhole did NOT land, this step proves nothing")


def clear_cache():
    keys = sh("docker", "exec", REDIS, "redis-cli", "--scan", "--pattern", "*:ans:*").stdout.split()
    for k in keys:
        sh("docker", "exec", REDIS, "redis-cli", "del", k)
    return len(keys)


def ask(question):
    body = json.dumps({"question": question, "stream": False}).encode()
    req = urllib.request.Request(
        API + "/api/v1/query", data=body, headers={"content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read().decode())
            return r.status, str(d.get("kind")), d.get("venue"), str(d.get("model_id"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode()[:300]
        slug = raw[:70]
        try:
            doc = json.loads(raw)
            slug = str(doc.get("title", "")) + " / " + str(doc.get("type", "")).rsplit("/", 1)[-1]
        except Exception:
            pass
        return e.code, "(http)", None, slug
    except Exception as e:
        return 0, "(transport)", None, str(e)[:80]


STEPS = [
    ([], "local-sglang", "baseline: the primary leg answers"),
    (["local-sglang"], "groq", "primary down -> first fallback takes over"),
    (["local-sglang", "groq"], "openai", "two down -> last resort takes over"),
    (["local-sglang", "groq", "openai"], None, "ALL down -> 503, never a fabricated answer"),
]


def main():
    print("")
    print("  FAILOVER DRILL (D4b) - breaking each leg in chain order")
    print("  " + "-" * 78)
    hosts_snapshot()
    results = []
    try:
        for i, (broken, expect, why) in enumerate(STEPS):
            blackhole(broken)
            verify_blocked(broken)
            if broken:
                time.sleep(POOL_DRAIN_SECONDS)
            clear_cache()
            code, kind, venue, model = ask(QUESTIONS[i])
            if expect is None:
                ok = code == 503
                got = "HTTP " + str(code) + " " + str(model)
                want = "HTTP 503 service-degraded"
            else:
                ok = venue == expect
                got = str(venue) + " (" + kind + ")"
                want = expect
            results.append(ok)
            print("  " + ("PASS" if ok else "FAIL") + "   broken: " + (", ".join(broken) or "nothing"))
            print("         want " + want)
            print("         got  " + got)
            print("         " + why)
            print("")

        # RECOVERY is half the drill. A chain that fails over and never comes back has
        # merely moved the outage. The breaker opens after 3 failures and holds a 30s
        # cooldown before admitting one probe, so the primary does NOT return instantly -
        # that delay is correct, and better seen here than during an incident.
        blackhole([])
        time.sleep(POOL_DRAIN_SECONDS)
        print("  RECOVERY - all legs restored, waiting for the breaker to close")
        started = time.time()
        back_after = None
        while time.time() - started < 120:
            clear_cache()
            code, kind, venue, model = ask(QUESTIONS[-1])
            if venue == "local-sglang":
                back_after = round(time.time() - started)
                break
            print("         still on " + str(venue) + " - breaker not closed yet")
            time.sleep(10)
        ok = back_after is not None
        results.append(ok)
        if ok:
            print("  PASS   primary reclaimed after ~" + str(back_after) + "s")
        else:
            print("  FAIL   primary never reclaimed within 120s")
    finally:
        # ALWAYS restore. A drill that leaves the system broken is an outage you caused.
        blackhole([])
        print("")
        print("  /etc/hosts restored")

    passed = sum(1 for r in results if r)
    print("  " + "-" * 78)
    print("  " + str(passed) + " passed, " + str(len(results) - passed) + " FAILED")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
