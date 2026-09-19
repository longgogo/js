# coding=utf-8
"""
NO影视 —— TVBox Python 蜘蛛（py 源）

站点：https://www.novipnoad.uk/（备用：klyingshi1.com，用户给定，实测对本机 403，自动跳过）
站型：WordPress 博客式影视站（post-format-video），路由如下
  分类  /{tid}/                              翻页 /{tid}/page/{pg}/
        tid ∈ tv, movie, anime, shows, music, short, other
        剧集分区 tid = tv/{hongkong|taiwan|western|japan|korea|thailand|turkey}
  详情  /{tid}/{id}.html
  搜索  /search/{utf8}/                      翻页 /search/{utf8}/page/{pg}/
  （HTML 属性普遍不带引号，正则一律按宽松写法）

★ 详情页内联 window.playInfo：
    电影   {vid:"ftn-xxxx", pkey:"...."}                    —— 单集
    剧集   {pkey:"...."} + 每集 <a data-vid=ftn-xxxx>E01..  —— pkey 全剧共享
  pkey 是 URL 编码态，必须**原样透传**（再编码会 %25 双重编码导致失败）。

★ 播放链路（逆向还原，全程纯 Python）：
  1) GET player.novipnoad.uk/v1/?url={vid}&pkey={pkey}&ref={详情路径}
     返回页含 params['device']='...' 和两段数值数组 + 状态机胶水代码
     （XOR 键为同名变量先后赋值两次，正则取 m2 位置附近**最后一次**赋值）；
  2) 数组1 XOR k1 = 浏览器指纹校验代码（含 DOM 布局测量，无法离线复算），
     但 stage2 = (数组2 ^ k2 - hash) & 0xFF **只依赖 hash 低 8 位**
     → 直接穷举 256 个值，解出含 ckey / vkey{ref,ip,time} 的 JS；
  3) GET enc-vod.oss-internal.novipnoad.uk/ftn/{nid}.js?ckey=&ref=&ip=&time=
     ※ 服务端校验请求头：v1 与 enc-vod 必须用**同一个 User-Agent**（桌面 UA），
        本机为 IPv6 临时地址时还要把两个请求**绑定同一源地址**，否则 "invalid request"；
     返回 var videoUrl=JSON.decrypt("base64密文")；
  4) JSON.decrypt 已离线破解 = base64 + 固定 2048 字节 keystream 异或
     （keystream 用全零密文从混淆 jquery.min.js 的 JSON.decrypt 里直接提取，
      实测跨视频/跨会话恒定）→ 得 {"code":200,"quality":[{"name":"1080P","url":"mp4"}]}
     直链为腾讯微云 ftn.qq.com 签名 MP4，parse:0 直出。
"""
import base64
import io
import json
import re
import socket
import ssl
import time
import http.client
import urllib.error
import urllib.parse
import urllib.request

from base.spider import Spider


class Spider(Spider):

    DEFAULT_HOST = "https://www.novipnoad.uk"
    # 备用域名（地址发布页给出；个别网络下可能 403，_get 会自动切换/跳过）
    HOSTS = ["https://www.novipnoad.uk", "https://klyingshi1.com"]
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    TIMEOUT = 20

    CLASSES = [
        ("tv", "电视剧"), ("movie", "电影"), ("anime", "动画"), ("shows", "综艺"),
        ("music", "音乐"), ("short", "短片"), ("other", "其他"),
        ("tv/hongkong", "港剧"), ("tv/taiwan", "台剧"), ("tv/western", "欧美剧"),
        ("tv/japan", "日剧"), ("tv/korea", "韩剧"), ("tv/thailand", "泰剧"),
        ("tv/turkey", "土耳其剧"),
    ]

    CARD = re.compile(
        r'href=(?:https?://[^/]*novipnoad[^/ \t]*)?/?((?:movie|tv|anime|shows|music|short|other)'
        r'(?:/[a-z]+)?/\d+)\.html[^>]*?title="([^"]*)"')
    IMG = re.compile(r'<img[^>]*>')
    SRC = re.compile(r'(?:data-original|src)=("[^"]+"|[^ >]+)')
    PLAYINFO = re.compile(r'window\.playInfo=\{([^}]*)\}')
    EP = re.compile(r'data-vid=(ftn-\d+)[^>]*>\s*(?:<i[^>]*></i>)?([^<]*)<')
    CIPHER = re.compile(r'JSON\.decrypt\("([A-Za-z0-9+/=]{40,})"\)')

    # enc-vod 响应用固定 keystream 异或加密（从站点 JSON.decrypt 提取，跨会话恒定）
    _KS_B64 = (
        "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")


    # ================= 基础 =================

    def getName(self):
        return "NO影视"

    def init(self, extend=""):
        host = (extend or "").strip()
        if not host:
            host = self.DEFAULT_HOST
        if not host.startswith("http"):
            host = "https://" + host
        self.host = host.rstrip("/")
        self._bad = set()
        self._ks = None
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def isVideoFormat(self, url):
        return True if re.search(r"\.(m3u8|mp4|flv)(\?|$)", url or "") else False

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ================= HTTP =================

    def _raw(self, url, referer=None, timeout=None):
        h = {"User-Agent": self.UA, "Accept-Language": "zh-CN"}
        if referer:
            h["Referer"] = referer
        req = urllib.request.Request(url)
        for k, v in h.items():
            req.add_header(k, v)
        return urllib.request.urlopen(req, timeout=timeout or self.TIMEOUT, context=self._ctx)

    def _text(self, url, referer=None, timeout=None):
        try:
            with self._raw(url, referer, timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            try:
                return (e.read() or b"").decode("utf-8", "ignore")
            except Exception:
                return ""
        except Exception:
            return ""

    def _get(self, path, referer=None, tries=2):
        """path 可为 '/xxx' 或完整 URL；当前域名失败自动切备用并记住坏域名。"""
        if path.startswith("http"):
            return self._text(path, referer)
        order = [self.host] + [x for x in self.HOSTS if x != self.host]
        order = [x for x in order if x not in self._bad] or list(self.HOSTS)
        best = ""
        for _ in range(tries):
            for h in order:
                t = self._text(h + path, referer or h + "/")
                if t and len(t) > 3000 and ">404" not in t[:200]:
                    if h != self.host:
                        self.host = h
                    return t
                if t and len(t) > len(best):
                    best = t
            time.sleep(0.4)
        return best

    # 源地址绑定（IPv6 临时地址轮换会导致 v1 与 enc-vod 出口 IP 不一致 → invalid request）
    def _src_addr(self):
        for probe, af in (("2400:3200::1", socket.AF_INET6), ("223.5.5.5", socket.AF_INET)):
            try:
                s = socket.socket(af, socket.SOCK_DGRAM)
                try:
                    s.connect((probe, 80))
                    return s.getsockname()[0]
                finally:
                    s.close()
            except Exception:
                continue
        return None

    def _hget(self, host, path, headers):
        """v1 / enc-vod 专用：优先绑定源地址 + IPv6，失败回退普通连接。"""
        hdrs = {"host": host}
        hdrs.update(headers)
        src = self._src_addr()
        if src:
            fam = socket.AF_INET6 if ":" in src else socket.AF_INET
            try:
                ip = socket.getaddrinfo(host, 443, fam, socket.SOCK_STREAM)[0][4][0]
                conn = http.client.HTTPSConnection(ip, context=self._ctx,
                                                   timeout=self.TIMEOUT,
                                                   source_address=(src, 0))
                conn.request("GET", path, headers=hdrs)
                r = conn.getresponse()
                data = r.read()
                conn.close()
                return r.status, data.decode("utf-8", "ignore")
            except Exception:
                pass
        conn = http.client.HTTPSConnection(host, context=self._ctx, timeout=self.TIMEOUT)
        conn.request("GET", path, headers=hdrs)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, data.decode("utf-8", "ignore")

    # ================= 列表 =================

    @staticmethod
    def _unesc(s):
        if not s:
            return ""
        s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
        return (s.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
                 .replace("&lt;", "<").replace("&gt;", ">").replace("&#8211;", "–")
                 .replace("&#8216;", "'").replace("&#8217;", "'").replace("&nbsp;", " "))

    @staticmethod
    def _clean(s):
        return re.sub(r"\s+", " ", (s or "")).strip()

    def _cards(self, html):
        out, seen = [], set()
        for m in self.CARD.finditer(html or ""):
            pid, name = m.group(1), self._clean(self._unesc(m.group(2)))
            if pid in seen or not name:
                continue
            seg = html[m.start():m.start() + 900]
            pic = ""
            mi = self.IMG.search(seg)
            if mi:
                ms = self.SRC.search(mi.group(0))
                if ms:
                    pic = self._unesc(ms.group(1).strip('"'))
                    if "loading." in pic:                    # 懒加载占位图
                        md = re.search(r'data-original=("[^"]+"|[^ >]+)', mi.group(0))
                        pic = self._unesc(md.group(1).strip('"')) if md else ""
            seen.add(pid)
            out.append({"vod_id": pid, "vod_name": name,
                        "vod_pic": pic if pic.startswith("http") else "",
                        "vod_remarks": ""})
        return out

    def homeContent(self, filter):
        return {"class": [{"type_id": t, "type_name": n} for t, n in self.CLASSES]}

    def homeVideoContent(self):
        return {"list": self._cards(self._get("/"))}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        path = "/%s/" % tid.strip("/") if pg == 1 else "/%s/page/%d/" % (tid.strip("/"), pg)
        lst = self._cards(self._get(path))
        return {"list": lst, "page": pg, "pagecount": 9999,
                "limit": len(lst) or 24, "total": 999999}

    def searchContent(self, key, quick, pg=1):
        key = self._clean(key)
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if not key:
            return {"list": [], "page": pg}
        path = "/search/%s/" % urllib.parse.quote(key, safe="")
        if pg > 1:
            path += "page/%d/" % pg
        return {"list": self._cards(self._get(path)), "page": pg}

    # ================= 详情 =================

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = str(vid).strip().strip("/")
        d = self._detail(vid)
        return {"list": [d]} if d else {"list": []}

    def _detail(self, pid):
        path = "/%s.html" % pid
        html = self._get(path)
        if not html:
            return None

        def one(pat, src=None):
            m = re.search(pat, src if src is not None else html, re.S)
            return self._clean(self._unesc(m.group(1))) if m else ""

        name = one(r'<h3><a[^>]*title="([^"]*)"') or one(r"<title>(.*?)</title>")
        name = re.sub(r"_?高清在线观看.*$", "", name).strip()

        pic = ""
        mog = re.search(r'<meta[^>]*og:image[^>]*>', html)
        if mog:
            mc = re.search(r'content=("[^"]+"|[^ >]+)', mog.group(0))
            if mc:
                pic = self._unesc(mc.group(1).strip('"'))
        if not pic.startswith("http"):
            i = html.find('class=item-thumbnail')
            if i < 0:
                i = html.find('class="item-thumbnail')
            if i >= 0:
                mi = self.IMG.search(html[i:i + 600])
                if mi:
                    ms = self.SRC.search(mi.group(0))
                    if ms:
                        pic = self._unesc(ms.group(1).strip('"'))
                        if "loading." in pic:
                            md = re.search(r'data-original=("[^"]+"|[^ >]+)', mi.group(0))
                            pic = self._unesc(md.group(1).strip('"')) if md else ""

        content = ""
        j = html.find("item-content")
        if j >= 0:
            seg = html[j:j + 6000]
            k = seg.find("在线播放")
            if k >= 0:
                seg = seg[:k]
            content = self._clean(self._unesc(re.sub(r"<[^>]+>", " ", seg)))
            content = re.sub(r"^(发布|分类|标签)[：:].*$", "", content).strip()

        mp = self.PLAYINFO.search(html)
        if not mp:
            return None
        info = dict(re.findall(r'(\w+):"([^"]*)"', mp.group(1)))
        pkey = info.get("pkey", "")
        year = one(r"\((19|20)\d{2}\)", html) or ""
        myear = re.search(r"\(((?:19|20)\d{2})\)", name)
        if myear:
            year = myear.group(1)

        lines, urls = [], []
        eps = self.EP.findall(html)
        if eps:
            items = []
            for v, t in eps:
                t = self._clean(t) or ("第%d集" % (len(items) + 1))
                items.append("%s$%s|%s|%s" % (t, v, pkey, pid))
            lines.append("播放列表")
            urls.append("#".join(items))
        elif info.get("vid"):
            lines.append("播放列表")
            urls.append("正片$%s|%s|%s" % (info["vid"], pkey, pid))
        if not urls:
            return None

        return {
            "vod_id": pid,
            "vod_name": name,
            "vod_pic": pic if pic.startswith("http") else "",
            "vod_content": content,
            "vod_year": year,
            "type_name": one(r'rel="category tag">([^<]+)<'),
            "vod_play_from": "$$$".join(lines),
            "vod_play_url": "$$$".join(urls),
        }

    # ================= 播放 =================

    def _keystream(self):
        if self._ks is None:
            try:
                self._ks = base64.b64decode(self._KS_B64)
            except Exception:
                self._ks = b""
        return self._ks

    def _decrypt(self, body):
        m = self.CIPHER.search(body or "")
        if not m:
            return None
        ks = self._keystream()
        if not ks:
            return None
        try:
            ct = base64.b64decode(m.group(1))
        except Exception:
            return None
        return bytes(b ^ ks[i % len(ks)] for i, b in enumerate(ct)).decode("utf-8", "ignore")

    @staticmethod
    def _parse_v1(html):
        """v1 页 → ckey, vkey(dict)。数组解码键为同名变量先后两次赋值。"""
        arrs = sorted([(n, v) for n, v in re.findall(r"(?:var\s+)?(\w+)=\[(\d+(?:,\d+)+)\]", html)
                       if len(v) > 150], key=lambda x: -len(x[1]))
        m2 = re.search(r"\[\w+\]\^(\w+)\)-\w+\)&0xFF", html)
        if m2 is None or len(arrs) < 2:
            raise RuntimeError("v1 glue parse fail")
        k2 = None
        for it in re.finditer(r"[\s,;]%s=(\d+)[;,]" % re.escape(m2.group(1)), html):
            if it.start() >= m2.start() - 200:
                k2 = int(it.group(1))
        a2 = [int(x) for x in arrs[1][1].split(",")]
        # 已知明文攻击：((n^k2)-h)&0xFF 只依赖 h 低 8 位 → 穷举 256 个值
        stage2 = None
        for hv in range(256):
            dec = "".join(chr(((n ^ k2) - hv) & 0xFF) for n in a2)
            if "ckey:" in dec and "vkey" in dec:
                stage2 = dec
                break
        if not stage2:
            raise RuntimeError("v1 256-sweep fail")
        vk = eval(re.search(r"vkey','(\{[^\']+\})'", stage2).group(1))
        ck = re.search(r"ckey:\s*'([0-9a-f]+)'", stage2).group(1).upper()
        return vk, ck

    def playerContent(self, flag, id, vipFlags):
        raw = (id or "").split("|")
        if len(raw) != 3:
            return {"parse": 1, "url": self.host + "/"}
        vid, pkey, ref = raw
        if pkey.startswith("http"):
            return {"parse": 0, "url": pkey, "header": {"User-Agent": self.UA}}
        ref = "/" + ref.strip("/") + ".html"      # v1 校验 ref 必须是真实详情路径
        sec = {
            "accept-language": "zh-CN",
            "sec-ch-ua": '"Microsoft Edge";v="153", "Not_A Brand";v="8", "Chromium";v="153"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "user-agent": self.UA,
        }
        try:
            u1 = ("/v1/?url=%s&pkey=%s&ref=%s"
                  % (vid, pkey, urllib.parse.quote(ref, safe="")))
            st1, b1 = self._hget("player.novipnoad.uk", u1,
                                 {"referer": self.host + "/", **sec})
            if st1 != 200:
                raise RuntimeError("v1 http %s" % st1)
            vk, ck = self._parse_v1(b1)
            u3 = ("/ftn/%s.js?ckey=%s&ref=%s&ip=%s&time=%s"
                  % (vid.split("-")[1], ck, urllib.parse.quote(vk["ref"], safe=""),
                     vk["ip"], vk["time"]))
            st3, b3 = self._hget("enc-vod.oss-internal.novipnoad.uk", u3,
                                 {"referer": "https://player.novipnoad.uk/", **sec})
            if st3 != 200:
                raise RuntimeError("enc-vod http %s" % st3)
            data = json.loads(self._decrypt(b3) or "{}")
            q = [x for x in (data.get("quality") or []) if x.get("url")]
            if data.get("code") != 200 or not q:
                raise RuntimeError("no quality: %s" % (data.get("msg") or ""))
            best = q[0]
            for x in q:                      # 优先非 VIP 的高码率
                if not x.get("vip") and int(x.get("height") or 0) >= int(best.get("height") or 0):
                    best = x
            return {"parse": 0, "url": best["url"].replace("\\/", "/"),
                    "header": {"User-Agent": self.UA,
                               "Referer": "https://player.novipnoad.uk/"}}
        except Exception:
            # 兜底：让 TVBox 走网页嗅探
            return {"parse": 1, "url": self.host + "/%s.html" % ref.strip("/"),
                    "header": {"User-Agent": self.UA}}

    # ================= 本地代理（无需） =================

    def localProxy(self, param):
        return None
