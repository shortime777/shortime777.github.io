import base64, datetime as dt, json, time, urllib.error, urllib.parse, urllib.request
# 클라우드 정기 루틴(인스타게시 환경)이 매시 돌리는 스크립트. queue.json 에서 시각이 지난 3시간 안 항목을 인스타·스레드에 올린다.
# 토큰 없음: 환경의 네트워크 시크릿이 graph.facebook.com / graph.threads.net 요청에 Authorization 헤더를 붙인다.
# 같은 첫 줄이 이미 올라가 있으면 건너뛴다(중복 방지). 스레드는 글자 500자 제한이라 문단 단위로 줄인다.
IG, TH = "17841470278953124", "40582119178070091"
SRC = ["https://raw.githubusercontent.com/shortime777/shortime777.github.io/main/queue.json?t=%d" % time.time(),
       "https://api.github.com/repos/shortime777/shortime777.github.io/contents/queue.json"]


def load_queue():
    for u in SRC:
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "shortime"}), timeout=60).read())
            return json.loads(base64.b64decode(j["content"])) if isinstance(j, dict) else j
        except Exception as e:
            print("queue read failed", u.split("?")[0], e)
    raise SystemExit("could not read queue")


def call(base, path, method="GET", **p):
    q = urllib.parse.urlencode(p)
    req = urllib.request.Request(base + path + ("?" + q if method == "GET" and q else ""), data=q.encode() if method == "POST" else None, method=method)
    try:
        return json.load(urllib.request.urlopen(req, timeout=90))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"API error {path}: {e.read().decode('utf-8', 'ignore')}")


def wait(base, cid, field):
    for _ in range(60):
        s = call(base, cid, fields=field).get(field)
        if s == "FINISHED":
            return
        if s == "ERROR":
            raise RuntimeError("processing error " + cid)
        time.sleep(4)
    raise RuntimeError("processing timeout " + cid)


def short(text, n=490):
    out = ""
    for para in text.split("\n\n"):
        if para.startswith("#") or para.startswith("출처"):
            continue
        if len(out) + len(para) + 2 > n:
            break
        out += ("\n\n" if out else "") + para
    return out or text[:n]


def post_ig(q):
    G = "https://graph.facebook.com/v21.0/"
    if len(q["images"]) == 1:
        cid = call(G, f"{IG}/media", "POST", image_url=q["images"][0], caption=q["caption"])["id"]
    else:
        kids = [call(G, f"{IG}/media", "POST", image_url=u, is_carousel_item="true")["id"] for u in q["images"]]
        for k in kids:
            wait(G, k, "status_code")
        cid = call(G, f"{IG}/media", "POST", media_type="CAROUSEL", children=",".join(kids), caption=q["caption"])["id"]
    wait(G, cid, "status_code")
    mid = call(G, f"{IG}/media_publish", "POST", creation_id=cid)["id"]
    for c in q.get("comments", [])[:2]:  # 게시 직후 우리 계정 댓글 2개(보충 정보 + 참여 질문)
        try:
            time.sleep(5)
            call(G, f"{mid}/comments", "POST", message=c)
        except Exception as e:
            print("comment failed:", e)
    return call(G, mid, fields="permalink").get("permalink")


def post_th(q):
    G = "https://graph.threads.net/v1.0/"
    text = short(q["caption"])
    if len(q["images"]) == 1:
        cid = call(G, f"{TH}/threads", "POST", media_type="IMAGE", image_url=q["images"][0], text=text)["id"]
    else:
        kids = [call(G, f"{TH}/threads", "POST", media_type="IMAGE", image_url=u, is_carousel_item="true")["id"] for u in q["images"][:20]]
        for k in kids:
            wait(G, k, "status")
        cid = call(G, f"{TH}/threads", "POST", media_type="CAROUSEL", children=",".join(kids), text=text)["id"]
    wait(G, cid, "status")
    mid = call(G, f"{TH}/threads_publish", "POST", creation_id=cid)["id"]
    return call(G, mid, fields="permalink").get("permalink")


PAGE = "1402403352962207"
FB = "https://graph.facebook.com/v21.0/"


def page_token():
    return call(FB, PAGE, fields="access_token")["access_token"]  # 헤더의 봇 키로 페이지 키를 받아 옴(만료 없음)


def post_fb(q):
    pt = page_token()
    if len(q["images"]) == 1:
        r = call(FB, f"{PAGE}/photos", "POST", url=q["images"][0], caption=q["caption"], access_token=pt)
        pid = r.get("post_id") or r["id"]
    else:
        ids = [call(FB, f"{PAGE}/photos", "POST", url=u, published="false", access_token=pt)["id"] for u in q["images"]]
        pid = call(FB, f"{PAGE}/feed", "POST", message=q["caption"], access_token=pt,
                   attached_media=json.dumps([{"media_fbid": i} for i in ids]))["id"]
    return call(FB, pid, fields="permalink_url", access_token=pt).get("permalink_url")


now = dt.datetime.now(dt.timezone.utc)
due = [q for q in load_queue() if dt.timedelta(0) <= now - dt.datetime.fromisoformat(q["time"]) < dt.timedelta(hours=3)]
print("due now:", [q["name"] for q in due] or "none")
if due:
    try:
        ig_done = [(m.get("caption") or "").strip() for m in call("https://graph.facebook.com/v21.0/", f"{IG}/media", fields="caption", limit=25).get("data", [])]
    except Exception as e:
        ig_done = None; print("instagram list failed:", e)
    try:
        th_done = [(m.get("text") or "").strip() for m in call("https://graph.threads.net/v1.0/", f"{TH}/threads", fields="text", limit=25).get("data", [])]
    except Exception as e:
        th_done = None; print("threads list failed:", e)
    try:
        fb_done = [(m.get("message") or "").strip() for m in call(FB, f"{PAGE}/posts", fields="message", limit=25, access_token=page_token()).get("data", [])]
    except Exception as e:
        fb_done = None; print("facebook list failed:", e)
for q in due:
    first = q["caption"].splitlines()[0]
    for name, done, fn in (("instagram", ig_done, post_ig), ("threads", th_done, post_th), ("facebook", fb_done, post_fb)):
        if done is None:
            continue
        if any(c.startswith(first) for c in done):
            print(f"{name} already posted:", q["name"]); continue
        try:
            print(f"{name} posted:", q["name"], fn(q))
        except Exception as e:
            print(f"{name} failed:", q["name"], e)
