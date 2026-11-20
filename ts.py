#!/usr/bin/env python3
# GHA runner Turnstile probe v3: real Chrome + stealth + longer wait + widget click + login probe
import os, sys, json, time, socket, subprocess, urllib.request, urllib.error, shutil

TOPIC = os.environ.get("TOPIC", "i42301ts-9f3a2c")
MODE = os.environ.get("MODE", "probe3")
BASE = os.environ.get("BASE", "https://yibuapi.com")
OUT = []
CAND_IPS = ["104.18.16.146", "104.18.17.146"]

def log(*a):
    line = " ".join(str(x) for x in a); print(line, flush=True); OUT.append(line)

def send(tag, text):
    text = str(text)
    for i in range(0, len(text), 3800):
        chunk = ("[%s %d] " % (tag, i // 3800 + 1)) + text[i:i+3800]
        try:
            req = urllib.request.Request("https://ntfy.sh/" + TOPIC, data=chunk.encode("utf-8", "replace"),
                                         method="POST", headers={"Title": tag[:60]})
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:
            print("NTFYERR", str(e)[:120], flush=True)

def egress():
    try: return urllib.request.urlopen("https://api.ipify.org", timeout=12).read().decode().strip()
    except Exception as e: return "ERR:" + str(e)[:80]

def curl_resolve(host, ip):
    try:
        p = subprocess.run(["curl", "-s", "-m", "10", "-o", "/dev/null", "-w", "%{http_code}",
                            "--resolve", "%s:443:%s" % (host, ip), "https://%s/" % host],
                           capture_output=True, text=True, timeout=15)
        return p.stdout.strip() or "000"
    except Exception:
        return "000"

STEALTH = r"""
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});
window.chrome=window.chrome||{runtime:{},loadTimes:function(){},csi:function(){}};
const origQuery=window.navigator.permissions&&window.navigator.permissions.query;
if(origQuery){window.navigator.permissions.query=function(p){return p&&p.name==='notifications'?Promise.resolve({state:'denied'}):origQuery.apply(navigator.permissions,arguments)};}
Object.defineProperty(navigator,'hardwareConcurrency',{get:()=>8});
Object.defineProperty(navigator,'deviceMemory',{get:()=>8});
const getParameter=WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter=function(p){if(p===37445)return 'Intel Inc.';if(p===37446)return 'Intel Iris OpenGL Engine';return getParameter.apply(this,arguments)};
"""

def main():
    log("RUN", os.environ.get("GITHUB_RUN_ID","?"), "MODE", MODE, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    eg = egress(); log("EGRESS", eg)
    bip = None
    for ip in CAND_IPS:
        st = curl_resolve("brunhild.challenges.cloudflare.com", ip)
        log("CURL_RESOLVE", ip, st)
        if st not in ("000", "") and bip is None: bip = ip
    log("BRUNHILD_IP", bip)
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    log("CHROME_PATH", chrome)

    from playwright.sync_api import sync_playwright
    args = ["--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled",
            "--window-size=1366,900","--lang=en-US"]
    if bip: args.append("--host-resolver-rules=MAP brunhild.challenges.cloudflare.com %s" % bip)

    token=None; reqs=[]; resps=[]; cons=[]
    with sync_playwright() as p:
        b = None
        if chrome:
            try:
                b = p.chromium.launch(headless=False, channel="chrome", args=args)
                log("LAUNCH", "channel=chrome")
            except Exception as e:
                log("LAUNCH_CHROME_ERR", str(e)[:150])
        if b is None:
            b = p.chromium.launch(headless=False, args=args); log("LAUNCH","bundled-chromium")
        c = b.new_context(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                          viewport={"width":1366,"height":900}, locale="en-US", ignore_https_errors=True)
        c.add_init_script(STEALTH)
        pg = c.new_page()
        pg.on("request", lambda r: reqs.append({"url":r.url,"post":r.post_data}) if "/api/user/login" in r.url else None)
        def on_resp(r):
            if "/api/user/login" in r.url:
                try: resps.append({"status":r.status,"body":r.text()[:400]})
                except Exception as e: resps.append({"status":r.status,"err":str(e)[:60]})
        pg.on("response", on_resp)
        pg.on("console", lambda m: cons.append("["+m.type+"] "+m.text[:160]))
        try: pg.goto(BASE+"/sign-in", wait_until="networkidle", timeout=70000)
        except Exception as e: log("GOTO_ERR", str(e)[:120])
        for i in range(20):
            try:
                if pg.evaluate("()=>document.querySelectorAll('input').length")>0: break
            except Exception: pass
            time.sleep(1)
        # DOM dump of turnstile container
        try:
            log("CFT_HTML", pg.evaluate("()=>{const e=document.querySelector('.cf-turnstile,[class*=turnstile],div[data-sitekey]');return e?e.outerHTML.slice(0,700):'NONE'}"))
            log("ALL_FRAMES", json.dumps(pg.evaluate("()=>Array.from(document.querySelectorAll('iframe')).map(f=>({src:f.src,vis:f.offsetWidth>0}))"), ensure_ascii=False)[:500])
        except Exception as e: log("DOM_ERR", str(e)[:120])
        # try clicking the widget container a few times
        for attempt in range(3):
            try:
                box = pg.evaluate("()=>{const e=document.querySelector('.cf-turnstile,[class*=turnstile],div[data-sitekey]');if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height}}")
                if box and box.get("w",0)>0:
                    pg.mouse.click(box["x"], box["y"]); log("CLICK_WIDGET", attempt, json.dumps(box)); time.sleep(2)
            except Exception as e: log("CLICK_ERR", str(e)[:100])
        # long poll
        last=""
        for i in range(150):
            try: token = pg.evaluate("()=>{try{return window.turnstile?window.turnstile.getResponse():null}catch(e){return null}}")
            except Exception: token=None
            if token: log("TOKEN_AT_S", i); break
            if i % 15 == 14:
                try:
                    hid = pg.evaluate("()=>{const e=document.querySelector('input[name=cf-turnstile-response]');return e?e.value.slice(0,20):'NA'}")
                    log("TICK", i, "hasT=", pg.evaluate("()=>!!window.turnstile"), "hidden=", hid)
                except Exception: pass
            time.sleep(1)
        log("TOKEN_LEN", len(token) if token else 0)
        if token: log("TOKEN_PREFIX", token[:24])
        try: pg.screenshot(path="signin3.png", full_page=True)
        except Exception: pass
        if token:
            # fill + submit real form
            try:
                pg.fill("input[name=username]", "__ts_probe")
                pg.fill("input[name=password]", "WrongPass__123")
            except Exception as e: log("FILL_ERR", str(e)[:100])
            try: pg.locator("button:has-text('Sign in')").first.click()
            except Exception as e: log("BTN_ERR", str(e)[:100])
            time.sleep(7)
            if not reqs:
                try:
                    r = pg.evaluate("""async (b)=>{const r=await fetch('/api/user/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return {status:r.status,body:(await r.text()).slice(0,400)}}""",
                                     {"username":"__ts_probe","password":"WrongPass__123","turnstile":token})
                    log("FETCH_turnstile =>", json.dumps(r, ensure_ascii=False)[:450])
                except Exception as e: log("FETCH_ERR", str(e)[:120])
        b.close()

    log("=== LOGIN_REQS ==="); [log(json.dumps(r,ensure_ascii=False)[:400]) for r in reqs]
    log("=== LOGIN_RESPS ==="); [log(json.dumps(r,ensure_ascii=False)[:500]) for r in resps]
    log("=== CONSOLE_err ==="); [log(l) for l in cons if any(k in l.lower() for k in ["turnstile","challenge","error","csp","captcha"])][:20]
    send("ts42301FINAL", "EGRESS=%s BIP=%s CHROME=%s TOKEN_LEN=%s RESPS=%s" % (eg,bip,bool(chrome),len(token) if token else 0, json.dumps(resps,ensure_ascii=False)[:600]))
    log("DONE")

if __name__ == "__main__":
    main()
