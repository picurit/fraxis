#!/usr/bin/env python3
"""Exhaustive smoke test for the refactored Fraxis Socket.IO server.

Covers: authentication (accept/reject), full document CRUD, doctype list/count/meta with
server-side limit clamping, method execution (plain whitelisted / async / async-progress /
async-generator streaming / failure), method enqueue (accepted + progress + terminal
success AND failure, single delivery, registry-gated progress), and >=20 concurrent
multi-session operations validating transaction isolation.
"""

import asyncio
import os
import sys
import time
import uuid

import socketio

URL = os.environ.get("SOCKETIO_SERVER", "http://localhost:8005")
GOOD_TOKEN = os.environ.get("SOCKETIO_AUTH_TOKEN", "0616168e1a15bcd:0136af1ccc46f4d")
BAD_TOKEN = f"{GOOD_TOKEN.split(':', 1)[0]}:wrongsecret"
NS_SYS, NS_DOC, NS_DT, NS_M = "/system", "/api/document", "/api/doctype", "/api/method"
ALL_NS = [NS_SYS, NS_DOC, NS_DT, NS_M]

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def is_ok(ack):
    return isinstance(ack, dict) and ack.get("is_success") is True and not ack.get("error_stack")


def is_err(ack):
    return isinstance(ack, dict) and ack.get("is_success") is False and bool(ack.get("error_stack"))


def no_stack_trace(ack):
    """No MessageTrace in any stack may carry a server stack_trace field."""
    for key in ("error_stack", "warning_stack", "info_stack"):
        for m in (ack or {}).get(key, []) or []:
            if "stack_trace" in m:
                return False
    return True


async def new_client(token, namespaces=ALL_NS):
    sio = socketio.AsyncClient(reconnection=False)
    await sio.connect(URL, auth={"token": token}, namespaces=namespaces, wait=True,
                      transports=["websocket"])
    return sio


async def test_auth():
    # Reject bad token
    rejected = False
    sio = socketio.AsyncClient(reconnection=False)
    try:
        await sio.connect(URL, auth={"token": BAD_TOKEN}, namespaces=[NS_SYS],
                          wait=True, transports=["websocket"])
    except Exception:
        rejected = True
    finally:
        try:
            await sio.disconnect()
        except Exception:
            pass
    check("auth: invalid token rejected", rejected)

    # Reject missing token
    rejected2 = False
    sio = socketio.AsyncClient(reconnection=False)
    try:
        await sio.connect(URL, namespaces=[NS_SYS], wait=True, transports=["websocket"])
    except Exception:
        rejected2 = True
    finally:
        try:
            await sio.disconnect()
        except Exception:
            pass
    check("auth: missing token rejected", rejected2)

    # Accept good token + ready payload bound to user
    ready = {}
    sio = socketio.AsyncClient(reconnection=False)

    @sio.on("system:connect:ready", namespace=NS_SYS)
    async def _ready(data):
        ready.update(data or {})

    await sio.connect(URL, auth={"token": GOOD_TOKEN}, namespaces=[NS_SYS],
                      wait=True, transports=["websocket"])
    await asyncio.sleep(0.4)
    check("auth: valid token accepted + identity bound", ready.get("user") == "Administrator",
          f"ready={ready}")
    ping = await sio.call("system:ping", {"hello": "x"}, namespace=NS_SYS, timeout=10)
    check("system:ping pong", is_ok(ping) and ping["data"]["message"] == "pong")
    await sio.disconnect()


async def test_document_crud():
    sio = await new_client(GOOD_TOKEN)
    title = f"smoke-{uuid.uuid4().hex[:8]}"

    # Collection-level broadcast capture (must cross namespace into /api/doctype room)
    changed = []
    updated = []
    deleted = []

    @sio.on("document:changed", namespace=NS_DT)
    async def _changed(data):
        changed.append(data)

    # subscribe to the collection on /api/doctype
    sub = await sio.call("doctype:subscribe", {"doctype": "ToDo"}, namespace=NS_DT, timeout=10)
    check("doctype:subscribe ok", is_ok(sub))

    # create
    ack = await sio.call("document:create", {"doctype": "ToDo", "data": {"description": title}},
                         namespace=NS_DOC, timeout=15)
    check("document:create ok", is_ok(ack) and ack["data"].get("name"), f"err={ack.get('error_stack')}")
    check("document:create no stack_trace leak", no_stack_trace(ack))
    name = ack["data"]["name"]

    # per-document subscribe to catch updated/deleted
    @sio.on("document:updated", namespace=NS_DOC)
    async def _updated(data):
        updated.append(data)

    @sio.on("document:deleted", namespace=NS_DOC)
    async def _deleted(data):
        deleted.append(data)

    subd = await sio.call("document:subscribe", {"doctype": "ToDo", "name": name},
                          namespace=NS_DOC, timeout=10)
    check("document:subscribe ok", is_ok(subd))

    # read
    rd = await sio.call("document:read", {"doctype": "ToDo", "name": name}, namespace=NS_DOC, timeout=10)
    check("document:read ok", is_ok(rd) and rd["data"]["name"] == name)

    # update
    up = await sio.call("document:update",
                        {"doctype": "ToDo", "name": name, "data": {"description": title + "-upd"}},
                        namespace=NS_DOC, timeout=15)
    check("document:update ok", is_ok(up) and up["data"]["description"] == title + "-upd")

    # delete
    dl = await sio.call("document:delete", {"doctype": "ToDo", "name": name}, namespace=NS_DOC, timeout=15)
    check("document:delete ok", is_ok(dl) and dl["data"]["name"] == name)

    await asyncio.sleep(1.0)
    check("broadcast: document:changed received (cross-namespace)",
          any(c.get("name") == name for c in changed), f"changed={changed}")
    check("broadcast: document:changed has create+update+delete actions",
          {"create", "update", "delete"}.issubset({c.get("action") for c in changed if c.get("name") == name}),
          f"actions={[c.get('action') for c in changed if c.get('name')==name]}")
    check("broadcast: document:updated to per-doc room", any(u.get("name") == name for u in updated))
    check("broadcast: document:deleted to per-doc room", any(d.get("name") == name for d in deleted))

    # read of deleted doc -> failure with sanitized error
    rd2 = await sio.call("document:read", {"doctype": "ToDo", "name": name}, namespace=NS_DOC, timeout=10)
    check("document:read deleted -> failure", is_err(rd2) and no_stack_trace(rd2))

    await sio.disconnect()


async def test_doctype_ops():
    sio = await new_client(GOOD_TOKEN)

    # limit clamp: request an absurd page size, server must cap at MAX_LIMIT (100)
    big = await sio.call("doctype:list", {"doctype": "DocType", "limit": 100000},
                         namespace=NS_DT, timeout=20)
    check("doctype:list ok", is_ok(big))
    check("doctype:list limit clamped to <=100", isinstance(big["data"], list) and len(big["data"]) <= 100,
          f"returned={len(big['data']) if isinstance(big['data'], list) else 'n/a'}")

    cnt = await sio.call("doctype:count", {"doctype": "ToDo"}, namespace=NS_DT, timeout=10)
    check("doctype:count ok", is_ok(cnt) and isinstance(cnt["data"]["count"], int))

    meta = await sio.call("doctype:meta", {"doctype": "ToDo"}, namespace=NS_DT, timeout=10)
    check("doctype:meta ok", is_ok(meta) and meta["data"].get("name") == "ToDo")

    await sio.disconnect()


async def test_method_execute():
    sio = await new_client(GOOD_TOKEN)

    # Capture every progress event delivered to this sid (the to-sid variant via
    # _emit_state deliberately carries no 'method' field; we account by time window).
    all_progress = []

    @sio.on("method:execute:progress", namespace=NS_M)
    async def _prog(data):
        all_progress.append(data)

    # plain whitelisted sync method (start+end only, NO progress)
    plain_before = len(all_progress)
    pc = await sio.call("method:execute", {"method": "fraxis.api.test_count", "args": {"doctype": "ToDo"}},
                        namespace=NS_M, timeout=20)
    check("method:execute plain whitelisted ok", is_ok(pc) and isinstance(pc["data"], int))
    await asyncio.sleep(0.4)
    check("plain method emitted NO progress (registry-gated)",
          len(all_progress) == plain_before, f"new={len(all_progress) - plain_before}")
    rt_before = len(all_progress)

    # async method, no ORM
    a1 = await sio.call("method:execute", {"method": "fraxis.api.async_simple_operation", "args": {"value": 21}},
                        namespace=NS_M, timeout=20)
    check("method:execute async ok", is_ok(a1) and a1["data"]["output"] == 42)

    # async method with ORM offloaded
    a2 = await sio.call("method:execute",
                        {"method": "fraxis.api.async_frappe_orm_operation", "args": {"doctype": "ToDo", "limit": 3}},
                        namespace=NS_M, timeout=20)
    check("method:execute async+ORM ok", is_ok(a2) and "total_count" in a2["data"])

    # async concurrent ORM
    a3 = await sio.call("method:execute",
                        {"method": "fraxis.api.async_concurrent_operations", "args": {}},
                        namespace=NS_M, timeout=20)
    check("method:execute async concurrent ok", is_ok(a3) and a3["data"].get("concurrent") is True)

    # async with realtime progress
    rt = await sio.call("method:execute",
                        {"method": "fraxis.api.async_with_progress_simulation", "args": {"steps": 4}},
                        namespace=NS_M, timeout=30)
    check("method:execute realtime ok", is_ok(rt) and rt["data"]["total_steps"] == 4)

    # async generator streaming
    vals = ["a", "b", "c", "d", "e"]
    g = await sio.call("method:execute",
                       {"method": "fraxis.api.get_async_iterator",
                        "args": {"values": vals, "min_ms": 10, "max_ms": 40}},
                       namespace=NS_M, timeout=30)
    check("method:execute async-gen streamed (bounded result)",
          is_ok(g) and g["data"].get("streamed") is True and g["data"].get("total_count") == len(vals),
          f"data={g.get('data')}")

    await asyncio.sleep(0.8)
    # 4 from async_with_progress_simulation + 5 from the async-generator stream = 9
    check("realtime progress events received", len(all_progress) - rt_before >= 9,
          f"new={len(all_progress) - rt_before}")

    # failure path (sanitized)
    f = await sio.call("method:execute",
                       {"method": "fraxis.api.async_error_handling",
                        "args": {"should_fail": True, "error_type": "runtime"}},
                       namespace=NS_M, timeout=20)
    check("method:execute failure path sanitized", is_err(f) and no_stack_trace(f))

    # non-whitelisted / unknown method rejected
    nf = await sio.call("method:execute", {"method": "os.system", "args": {"command": "echo hi"}},
                        namespace=NS_M, timeout=20)
    check("method:execute non-whitelisted rejected", is_err(nf))

    await sio.disconnect()


async def _await_event(holder, key, timeout):
    start = time.time()
    while time.time() - start < timeout:
        if holder.get(key):
            return True
        await asyncio.sleep(0.1)
    return False


async def test_method_enqueue_success():
    sio = await new_client(GOOD_TOKEN)
    events = {"accepted": [], "progress": [], "success": [], "failure": []}

    @sio.on("method:enqueue:accepted", namespace=NS_M)
    async def _acc(d): events["accepted"].append(d)

    @sio.on("method:enqueue:progress", namespace=NS_M)
    async def _pr(d): events["progress"].append(d)

    @sio.on("method:enqueue:success", namespace=NS_M)
    async def _su(d): events["success"].append(d)

    @sio.on("method:enqueue:failure", namespace=NS_M)
    async def _fa(d): events["failure"].append(d)

    ack = await sio.call("method:enqueue",
                         {"method": "fraxis.api.long_running_sync_job", "args": {"iterations": 4}},
                         namespace=NS_M, timeout=20)
    check("method:enqueue ack has task_id", is_ok(ack) and ack["data"].get("task_id"), f"ack={ack}")
    task_id = ack["data"]["task_id"]

    got = await _await_event(events, "success", timeout=30)
    await asyncio.sleep(0.5)
    check("enqueue: accepted event received (distinct from completion)", len(events["accepted"]) >= 1)
    check("enqueue: progress events received", len(events["progress"]) >= 4, f"count={len(events['progress'])}")
    check("enqueue: terminal success received", got and len(events["success"]) == 1,
          f"success={events['success']}")
    check("enqueue: success carries real result (not task_id)",
          got and isinstance(events["success"][0].get("result"), dict)
          and events["success"][0]["result"].get("completed") is True,
          f"result={events['success'][0].get('result') if events['success'] else None}")
    # single delivery: each progress tick appears once (no duplicate task_id+percent pairs)
    seen = [(p.get("task_id"), p.get("percent")) for p in events["progress"]]
    check("enqueue: progress delivered exactly once (no duplicates)", len(seen) == len(set(seen)),
          f"seen={seen}")
    check("enqueue: no failure emitted on success", len(events["failure"]) == 0)

    await sio.disconnect()


async def test_method_enqueue_failure():
    sio = await new_client(GOOD_TOKEN)
    events = {"success": [], "failure": []}

    @sio.on("method:enqueue:success", namespace=NS_M)
    async def _su(d): events["success"].append(d)

    @sio.on("method:enqueue:failure", namespace=NS_M)
    async def _fa(d): events["failure"].append(d)

    ack = await sio.call("method:enqueue",
                         {"method": "fraxis.api.failing_sync_job", "args": {"message": "boom"}},
                         namespace=NS_M, timeout=20)
    check("enqueue(failing): accepted ack", is_ok(ack) and ack["data"].get("task_id"))

    got = await _await_event(events, "failure", timeout=30)
    await asyncio.sleep(0.5)
    check("enqueue: terminal FAILURE received (not masqueraded as success)",
          got and len(events["failure"]) == 1, f"failure={events['failure']}")
    check("enqueue: NO false success on failure", len(events["success"]) == 0,
          f"success={events['success']}")
    check("enqueue: failure carries error message",
          got and "boom" in str(events["failure"][0].get("error", "")), f"failure={events['failure']}")

    await sio.disconnect()


async def test_enqueue_plain_no_progress():
    """A plain whitelisted method enqueued gets accepted + terminal, but NO progress."""
    sio = await new_client(GOOD_TOKEN)
    events = {"progress": [], "success": [], "failure": []}

    @sio.on("method:enqueue:progress", namespace=NS_M)
    async def _pr(d): events["progress"].append(d)

    @sio.on("method:enqueue:success", namespace=NS_M)
    async def _su(d): events["success"].append(d)

    @sio.on("method:enqueue:failure", namespace=NS_M)
    async def _fa(d): events["failure"].append(d)

    ack = await sio.call("method:enqueue",
                         {"method": "fraxis.api.test_count", "args": {"doctype": "ToDo"}},
                         namespace=NS_M, timeout=20)
    check("enqueue(plain): accepted ack", is_ok(ack))
    await _await_event(events, "success", timeout=20)
    await asyncio.sleep(0.5)
    check("enqueue(plain): terminal success received", len(events["success"]) == 1)
    check("enqueue(plain): NO progress events (registry-gated)", len(events["progress"]) == 0,
          f"count={len(events['progress'])}")
    await sio.disconnect()


async def test_concurrency(n=25):
    """>=20 concurrent creates across multiple sessions; verify isolation + consistency."""
    # baseline count via its own client
    base_client = await new_client(GOOD_TOKEN)
    base = await base_client.call("doctype:count", {"doctype": "ToDo"}, namespace=NS_DT, timeout=15)
    baseline = base["data"]["count"]

    # 5 independent client sessions
    clients = await asyncio.gather(*[new_client(GOOD_TOKEN, [NS_DOC, NS_DT]) for _ in range(5)])
    tag = f"conc-{uuid.uuid4().hex[:6]}"

    async def create_one(i):
        c = clients[i % len(clients)]
        return await c.call("document:create",
                            {"doctype": "ToDo", "data": {"description": f"{tag}-{i}"}},
                            namespace=NS_DOC, timeout=30)

    t0 = time.time()
    acks = await asyncio.gather(*[create_one(i) for i in range(n)], return_exceptions=True)
    elapsed = time.time() - t0

    oks = [a for a in acks if isinstance(a, dict) and is_ok(a)]
    names = {a["data"]["name"] for a in oks}
    check(f"concurrency: all {n} concurrent creates succeeded", len(oks) == n,
          f"ok={len(oks)}/{n} elapsed={elapsed:.2f}s")
    check("concurrency: every created doc has a unique name (no lost updates/corruption)",
          len(names) == n, f"unique={len(names)}")

    after = await base_client.call("doctype:count", {"doctype": "ToDo"}, namespace=NS_DT, timeout=15)
    check("concurrency: DB count increased by exactly N (transaction isolation)",
          after["data"]["count"] == baseline + n,
          f"baseline={baseline} after={after['data']['count']} expected={baseline+n}")

    # cleanup
    async def del_one(i, nm):
        c = clients[i % len(clients)]
        return await c.call("document:delete", {"doctype": "ToDo", "name": nm}, namespace=NS_DOC, timeout=30)

    dels = await asyncio.gather(*[del_one(i, nm) for i, nm in enumerate(names)], return_exceptions=True)
    dok = [d for d in dels if isinstance(d, dict) and is_ok(d)]
    check("concurrency: cleanup deleted all created docs", len(dok) == n, f"deleted={len(dok)}/{n}")

    final = await base_client.call("doctype:count", {"doctype": "ToDo"}, namespace=NS_DT, timeout=15)
    check("concurrency: final count back to baseline", final["data"]["count"] == baseline,
          f"final={final['data']['count']} baseline={baseline}")

    for c in clients + [base_client]:
        await c.disconnect()


async def test_concurrent_methods(n=24):
    """>=20 concurrent method:execute calls mixing plain/async methods across sessions."""
    clients = await asyncio.gather(*[new_client(GOOD_TOKEN, [NS_M]) for _ in range(4)])

    async def call_one(i):
        c = clients[i % len(clients)]
        if i % 3 == 0:
            return await c.call("method:execute",
                                {"method": "fraxis.api.test_count", "args": {"doctype": "ToDo"}},
                                namespace=NS_M, timeout=30)
        elif i % 3 == 1:
            return await c.call("method:execute",
                                {"method": "fraxis.api.async_simple_operation", "args": {"value": i}},
                                namespace=NS_M, timeout=30)
        else:
            return await c.call("method:execute",
                                {"method": "fraxis.api.async_frappe_orm_operation",
                                 "args": {"doctype": "ToDo", "limit": 2}},
                                namespace=NS_M, timeout=30)

    t0 = time.time()
    acks = await asyncio.gather(*[call_one(i) for i in range(n)], return_exceptions=True)
    elapsed = time.time() - t0
    oks = [a for a in acks if isinstance(a, dict) and is_ok(a)]
    check(f"concurrency(methods): all {n} concurrent executes succeeded", len(oks) == n,
          f"ok={len(oks)}/{n} elapsed={elapsed:.2f}s")
    # verify async multiply results are correct (no cross-task data bleed)
    multiplies = {i: a for i, a in enumerate(acks)
                  if isinstance(a, dict) and is_ok(a) and isinstance(a.get("data"), dict)
                  and a["data"].get("operation") == "multiply_by_2"}
    bleed = [i for i, a in multiplies.items() if a["data"]["output"] != i * 2]
    check("concurrency(methods): async results correct (no cross-task bleed)", not bleed,
          f"mismatched={bleed}")
    for c in clients:
        await c.disconnect()


async def main():
    print("=" * 70)
    print("FRAXIS EXHAUSTIVE SMOKE TEST")
    print("=" * 70)
    await test_auth()
    await test_document_crud()
    await test_doctype_ops()
    await test_method_execute()
    await test_method_enqueue_success()
    await test_method_enqueue_failure()
    await test_enqueue_plain_no_progress()
    await test_concurrency(25)
    await test_concurrent_methods(24)

    print("=" * 70)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"TOTAL: {passed}/{len(results)} passed")
    if failed:
        print("FAILURES:")
        for n, d in failed:
            print(f"  - {n} :: {d}")
    print("=" * 70)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
