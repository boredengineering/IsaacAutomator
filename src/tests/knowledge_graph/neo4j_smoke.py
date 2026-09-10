"""Opt-in real Docker smoke: uses and removes only its fresh isolated project.

Run with python3 src/tests/knowledge_graph/neo4j_smoke.py after building the image.
Never includes credentials or server logs in test output.
"""
import json
import os
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / ".devcontainer/docker-compose.yml"


def main():
    project = "isaacautomator-neo4j-test-" + uuid.uuid4().hex[:12]
    marker = uuid.uuid4().hex
    env = dict(os.environ, ISAAC_NEO4J_HTTP_PORT="0", ISAAC_NEO4J_BOLT_PORT="0")
    compose = ["docker", "compose", "--env-file", "/dev/null", "-f", str(COMPOSE), "-p", project]
    stage = "start"

    def run(args, data=None, timeout=60):
        result = subprocess.run(args, input=data, text=True, capture_output=True, env=env, timeout=timeout)
        if result.returncode:
            raise RuntimeError("operation failed; diagnostic output withheld")
        return result.stdout

    def container(service="automator-neo4j"):
        value = run(compose + ["ps", "-q", service]).strip()
        if not value or not all(c in "0123456789abcdef" for c in value):
            raise RuntimeError("unexpected container identifier")
        return value

    def query(cid, statement, parameters=None):
        code = (
            "import sys,json; sys.path.insert(0,'/opt/automator-neo4j'); "
            "from healthcheck import transaction; p=json.load(sys.stdin); "
            "print(json.dumps(transaction(p['statement'],p['parameters'])))"
        )
        return json.loads(run(["docker", "exec", "-i", cid, "python3", "-c", code],
                              json.dumps({"statement": statement, "parameters": parameters or {}})))

    try:
        run(compose + ["up", "-d", "--no-deps", "--no-build", "--wait", "--wait-timeout", "180", "automator-neo4j", "neo4j-gateway"], timeout=210)
        cid = container()
        stage = "isolation"
        info = json.loads(run(["docker", "inspect", cid]))[0]
        assert info["State"]["Health"]["Status"] == "healthy"
        assert info["Config"]["User"] == "7474:7474"
        assert info["HostConfig"]["CapDrop"] == ["ALL"]
        assert "no-new-privileges:true" in info["HostConfig"]["SecurityOpt"]
        assert info["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped"
        assert info["HostConfig"]["Memory"] == 2 * 1024**3
        assert len(info["NetworkSettings"]["Networks"]) == 1
        network = next(iter(info["NetworkSettings"]["Networks"]))
        assert json.loads(run(["docker", "network", "inspect", network]))[0]["Internal"]
        assert not info["HostConfig"]["PortBindings"]
        gateway = json.loads(run(["docker", "inspect", container("neo4j-gateway")]))[0]
        assert gateway["Config"]["User"] == "65532:65532"
        assert gateway["HostConfig"]["ReadonlyRootfs"]
        assert not gateway["Mounts"]
        assert all(binding["HostIp"] == "127.0.0.1"
                   for bindings in gateway["NetworkSettings"]["Ports"].values() for binding in bindings)
        assert all(mount["Type"] == "volume" for mount in info["Mounts"])
        assert {mount["Destination"] for mount in info["Mounts"]} == {"/data", "/logs", "/automator-secrets"}
        assert not any(value.startswith(("NEO4J_AUTH=", "NEO4J_AUTH_FILE=", "NEO4J_AUTH_PATH=", "NEO4J_PLUGINS="))
                       for value in info["Config"]["Env"])
        stage = "authentication"
        code = (
            "import urllib.request,urllib.error; "
            "r=urllib.request.Request('http://127.0.0.1:7474/db/neo4j/tx/commit',"
            "data=b'{\"statements\":[{\"statement\":\"RETURN 1\"}]}',"
            "headers={'Content-Type':'application/json'}); "
            "opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));\n"
            "try: opener.open(r,timeout=5); raise SystemExit(1)\n"
            "except urllib.error.HTTPError as e: raise SystemExit(0 if e.code==401 else 2)"
        )
        run(["docker", "exec", cid, "python3", "-c", code])
        stage = "host-loopback"
        published_port = int(gateway["NetworkSettings"]["Ports"]["7474/tcp"][0]["HostPort"])
        host_code = code.replace("127.0.0.1:7474", "127.0.0.1:" + str(published_port))
        run(["docker", "run", "--rm", "--network", "host", "--entrypoint", "python3",
             info["Image"], "-c", host_code])
        stage = "write"
        result = query(cid, "CREATE (n:AutomatorSmoke {marker:$marker}) RETURN n.marker", {"marker": marker})
        assert not result["errors"] and result["results"][0]["data"][0]["row"] == [marker]
        stage = "recreate"
        run(compose + ["up", "-d", "--no-deps", "--no-build", "--force-recreate", "--wait", "--wait-timeout", "180", "automator-neo4j", "neo4j-gateway"], timeout=210)
        next_cid = container()
        assert next_cid != cid
        result = query(next_cid, "MATCH (n:AutomatorSmoke {marker:$marker}) RETURN n.marker", {"marker": marker})
        assert result["results"][0]["data"][0]["row"] == [marker]
        stage = "file-import-denial"
        code = (
            "import sys;sys.path.insert(0,'/opt/automator-neo4j');from healthcheck import transaction;\n"
            "try:\n r=transaction(\"LOAD CSV FROM 'file:///etc/passwd' AS row RETURN row\");"
            " assert r.get('errors')\n"
            "except RuntimeError: pass"
        )
        run(["docker", "exec", next_cid, "python3", "-c", code])
        stage = "egress"
        code = (
            "import socket;\n"
            "try:\n s=socket.create_connection(('1.1.1.1',443),timeout=2);s.close();raise SystemExit(1)\n"
            "except OSError: pass"
        )
        run(["docker", "exec", next_cid, "python3", "-c", code])
        print(json.dumps({"status": "passed", "authenticated_read_write": True,
                          "unauthenticated_denied": True, "persistence_after_recreation": True,
                          "private_nonroot_service": True, "file_import_denied": True,
                          "host_loopback_reachable": True,
                          "internet_probe_blocked": True}))
        return 0
    except (OSError, ValueError, RuntimeError, AssertionError, KeyError, TypeError, subprocess.TimeoutExpired):
        print(json.dumps({"status": "failed", "stage": stage, "message": "No credentials or logs emitted."}))
        return 1
    finally:
        # Only this invocation's random project: never remove normal dev/Arena volumes.
        result = subprocess.run(compose + ["down", "--volumes", "--remove-orphans"],
                                env=env, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError("isolated test project cleanup failed: " + project)


if __name__ == "__main__":
    raise SystemExit(main())
