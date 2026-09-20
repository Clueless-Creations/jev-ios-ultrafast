"""MobAI HTTP/DSL device adapter for Jev.

Jev remains the decision engine. MobAI owns device discovery, leases, semantic
predicates, bridge lifecycle, local/remote/cloud routing, and device execution.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, os, re, time, urllib.error, urllib.parse, urllib.request, uuid

from .device import DeviceError, StaleObservation


class MobAIError(DeviceError):
    pass


@dataclass(frozen=True)
class MobAISnapshot:
    elements: list[dict]
    labels: list[str]
    screen_hash: str
    pid: int = 0
    observed_at: float = 0.0
    observation_id: str = ""

    def targets(self, kind):
        allowed = {"input"} if kind == "type" else {"button","link","cell","input","switch","text"}
        return {e["id"]: e["label"] or e["kind"] for e in self.elements
                if e["enabled"] and e["kind"].lower() in allowed and (kind != "type" or not e["value"])}

    def model_state(self):
        compact=[{k:e[k] for k in ("id","kind","label","value","enabled")} for e in self.elements]
        return {"screen_hash":self.screen_hash,"elements":compact,
                "tap_targets":self.targets("tap"),"type_targets":self.targets("type")}

    def as_dict(self):
        return {**self.model_state(),"labels":self.labels,"pid":0,"observed_at":self.observed_at}


_COMPACT = re.compile(r'^\s*\[(\d+)\]\s+([A-Za-z][A-Za-z0-9_]*)\s*(?:"([^"]*)")?\s*(?:#([^\s\[]+))?\s*(.*)$')
_CONTENT = re.compile(r'content="([^"]*)"')


def _parse_tree(tree):
    """Parse MobAI compact UI tree into Jev's transport-neutral snapshot."""
    if not isinstance(tree, str):
        raise MobAIError("MobAI observation did not return a compact UI tree")
    elements=[]
    seen={}
    for raw in tree.splitlines():
        m=_COMPACT.match(raw)
        if not m:
            continue
        index, kind, label, aid, tail=m.groups()
        label=label or ""
        value=(_CONTENT.search(tail).group(1) if _CONTENT.search(tail) else "")
        lower=tail.lower()
        enabled=not any(x in lower for x in ("disabled","enabled=false"))
        secure=any(x in lower for x in ("secure","password"))
        if secure:
            value="[redacted]"
        base=(kind.lower(),label,aid or "")
        occurrence=seen.get(base,0); seen[base]=occurrence+1
        predicate={"accessibility_id":aid} if aid else {"type":kind.lower(),"text":label,"index":occurrence}
        target=hashlib.sha256(json.dumps([base,occurrence],sort_keys=True).encode()).hexdigest()[:12]
        elements.append({"id":target,"kind":kind.lower(),"label":label,"value":value,
                         "enabled":enabled,"secure":secure,"predicate":predicate})
    if not elements:
        raise MobAIError("MobAI compact UI tree contained no parseable semantic elements")
    public=[{k:v for k,v in e.items() if k!="predicate"} for e in elements]
    digest=hashlib.sha256(json.dumps(public,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return MobAISnapshot(elements,[e["label"] for e in elements if e["label"]],digest,0,time.time(),uuid.uuid4().hex)


class MobAIClient:
    def __init__(self, base_url=None, token=None, timeout=60):
        self.base=(base_url or os.environ.get("MOBAI_URL") or "http://127.0.0.1:8686/api/v1").rstrip("/")
        self.token=token if token is not None else os.environ.get("MOBAI_TOKEN")
        self.timeout=timeout

    def request(self, method, path, body=None, lease=None):
        data=None if body is None else json.dumps(body,separators=(",",":")).encode()
        headers={"Content-Type":"application/json"}
        if self.token:
            headers["Authorization"]="Bearer "+self.token
        if lease:
            headers["X-Lease-Token"]=lease
        req=urllib.request.Request(self.base+path,data=data,headers=headers,method=method)
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as resp:
                raw=resp.read(8_000_001)
        except urllib.error.HTTPError as exc:
            code=exc.code
            raise MobAIError(f"MobAI HTTP {code}") from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise MobAIError("MobAI API unavailable or timed out") from None
        if len(raw)>8_000_000:
            raise MobAIError("MobAI response exceeded 8 MB")
        try:
            return json.loads(raw) if raw else None
        except (UnicodeError,json.JSONDecodeError):
            raise MobAIError("MobAI returned invalid JSON") from None


class MobAIDevice:
    """Device protocol backed by MobAI DSL v0.2 and exclusive device claims."""
    def __init__(self, device_id, bundle_id, *, base_url=None, token=None, app_ref=None, holder="jev-ios"):
        if not isinstance(device_id,str) or not device_id.strip():
            raise MobAIError("MobAI device ID is required")
        self.device_id,self.bundle_id=device_id,bundle_id
        self.client=MobAIClient(base_url,token)
        self.holder=holder
        self.app_ref=app_ref
        self.lease=None
        self._consumed=set()

    def __enter__(self):
        claim=self.client.request("POST","/devices/claim",
                                  {"device":self.device_id,"holder":self.holder,
                                   "clientId":"jev-ios-"+uuid.uuid4().hex})
        if not isinstance(claim,dict) or not claim.get("leaseToken"):
            raise MobAIError("MobAI did not return a device lease")
        self.lease=claim["leaseToken"]
        self.client.request("POST",f"/devices/{urllib.parse.quote(self.device_id,safe='')}/bridge/start",\n                            ({"app":self.app_ref} if self.app_ref else {}),self.lease)
        return self

    def __exit__(self,*_):
        token,self.lease=self.lease,None
        if token:
            try:self.client.request("POST","/devices/release",{"leaseToken":token})
            except DeviceError:pass

    def _dsl(self,steps):
        body={"version":"0.2","steps":steps}
        return self.client.request("POST",f"/devices/{urllib.parse.quote(self.device_id,safe='')}/dsl/execute",body,self.lease)

    def reset(self,launch_args=()):
        self._dsl([{"action":"open_app","bundle_id":self.bundle_id,"fresh":True,
                    **({"arguments":list(launch_args)} if launch_args else {})},
                   {"action":"wait_for","stable":True,"timeout_ms":5000}])
        self._consumed.clear()

    def observe(self):
        result=self._dsl([{"action":"observe","include":["ui_tree"],"only_visible":True,"compact":True}])
        try:
            step=result["step_results"][-1]["result"]
            observations=step["observations"]
            native=observations.get("native") or next(iter(observations.values()))
            tree=native["ui_tree"]
        except (KeyError,IndexError,TypeError,StopIteration):
            raise MobAIError("MobAI observation envelope was incomplete") from None
        return _parse_tree(tree)

    def execute(self,snapshot,decision,text_values):
        if snapshot.observation_id in self._consumed:
            raise MobAIError("This observation already dispatched an action")
        current=self.observe()
        if current.screen_hash!=snapshot.screen_hash:
            raise StaleObservation("MobAI UI changed before action")
        operation=decision.get("operation")
        steps=[]
        if operation in ("TAP","TYPE_TEXT"):
            target=decision.get("target")
            match=next((e for e in current.elements if e["id"]==target),None)
            if not match or target not in current.targets("tap" if operation=="TAP" else "type"):
                raise MobAIError("Decision does not select an observed MobAI target")
            if operation=="TAP":
                steps.append({"action":"tap","predicate":match["predicate"]})
            else:
                value=text_values.get(decision.get("text_key"))
                if not isinstance(value,str) or not value:
                    raise MobAIError("Typing requires caller-supplied text")
                steps.append({"action":"type","text":value,"predicate":match["predicate"]})
        elif operation in ("SCROLL_UP","SCROLL_DOWN"):
            steps.append({"action":"scroll","direction":"up" if operation=="SCROLL_UP" else "down","amount":"page","max_scrolls":1})
        else:
            raise MobAIError("Unsupported MobAI operation")
        self._consumed.add(snapshot.observation_id)
        steps += [{"action":"wait_for","stable":True,"timeout_ms":3000},
                  {"action":"observe","include":["ui_tree"],"only_visible":True,"compact":True}]
        started=time.monotonic()
        try:
            self._dsl(steps)
        except DeviceError:
            raise MobAIError("MobAI action outcome is uncertain; do not replay") from None
        after=self.observe()
        return {"operation":operation,"target":decision.get("target"),
                "before_hash":current.screen_hash,"after_hash":after.screen_hash,
                "pid":0,"duration_ms":round((time.monotonic()-started)*1000),
                "observed_at":after.observed_at}

    def screenshot(self,path):
        raise MobAIError("Use MobAI report artifacts for screenshots; direct transfer is not implemented")


def list_mobai_devices(*,base_url=None,token=None):
    result=MobAIClient(base_url,token).request("GET","/devices")
    if not isinstance(result,list):
        raise MobAIError("MobAI device listing was invalid")
    return result
