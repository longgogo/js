# coding=utf-8
"""
TVB云播 —— TVBox Python 蜘蛛（py 源）

站点：http://www.viptvb06.com
站型：海洋CMS（SeaCMS）+ mytheme（myui 系）模板，路由如下
  分类  /vod/type/id/{tid}.html              翻页 /vod/type/id/{tid}/page/{pg}.html
  详情  /vod/detail/id/{id}.html
  播放  /vod/play/id/{id}/sid/{sid}/nid/{nid}.html
  搜索  /vod/search/wd/{utf8}.html           （站点搜索不支持翻页）

★ 全站套「滑动验证」WAF（任意路径 403 + 0.9KB 的 <title>滑动验证</title> 页）。
  滑块根本不用拖：挑战脚本里写死了 key / value，只要 GET
  /xxxx_yanzheng_huadong.php?key=<key>&value=md5(逐字符 charCode+1 拼接)
  服务端就会 Set-Cookie 下发一个随机 cookie（响应 body 就是那个 cookie 的**名字**），
  带上它全站立刻 200。该 cookie 实测约 30 秒失效 → 本文件把解算**内置**、
  失效自动重取，这正是 py 源相对 XBPQ 版的最大价值：XBPQ 只能人工定期重跑解算脚本，
  而这里用户什么都不用管。

★ 播放：播放页里有 player_data={"encrypt":0,...,"url":"...","from":"..."}。
  6 条线路里 4 条 url 直接是明文 mp4 / m3u8（直出）；另 2 条
  （4K线路 zijianm3u8、国内高速新 vwnet）给的是 token，
  用站点 /static/js/playerconfig.js 里 player_list[from].parse 指到的解析接口
  换一次（返回页里 var playUrl="真实地址"），即可拿到 HLS 直链。
  → 六条线路**全部 parse=0 直出**，不需要 TVBox 嗅探。
"""
import hashlib
import json
import re
import time
import urllib.parse

from base.spider import Spider


class Spider(Spider):

    DEFAULT_HOST = "http://www.viptvb06.com"
    UA = ("Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/126.0.0.0 Mobile Safari/537.36")
    WAF_TTL = 22          # 滑动验证 cookie 实测约 30s 失效，留点余量

    # 站点播放器配置里解析接口的兜底表（正常会从 playerconfig.js 现读，这里只是防读取失败）
    PARSE_MAP = {
        "mp4": "http://104.233.148.69:666/index.php?url=",
        "mytvb": "http://104.233.148.69:666/index.php?url=",
        "hkm3u8": "http://104.233.148.69:666/index.php?url=",
        "13yun": "http://104.233.148.69:666/index.php?url=",
        "189d": "http://104.233.148.69:666/index.php?url=",
        "zijianm3u8": "http://104.233.148.69:666/index2.php?url=",
        "co": "http://104.233.148.69:666/index3.php?url=",
        "vwnet": "http://104.233.148.69:666/index3.php?url=",
        "yunjie": "http://104.233.148.69:666/index3.php?url=",
        "NSYS": "http://104.233.148.69:666/index3.php?url=",
        "1080zyk": "http://104.233.148.69:666/indexzy.php?url=",
        "lzm3u8": "http://104.233.148.69:666/indexzy.php?url=",
        "bfzym3u8": "http://104.233.148.69:666/indexzy.php?url=",
        "ffm3u8": "http://104.233.148.69:666/indexzy.php?url=",
        "dbm3u8": "http://104.233.148.69:666/indexzy.php?url=",
        "mytv": "http://104.233.148.69:808/hktvua.php?url=",
    }

    LIST_UL = re.compile(r'(?s)<ul class="myui-vodlist clearfix">(.*?)</ul>')
    CARD_ID = re.compile(r'href="/vod/detail/id/(\d+)\.html"')
    CARD_TITLE = re.compile(r'title="([^"]*)"')
    CARD_PIC = re.compile(r'data-original="([^"]*)"')
    CARD_REM = re.compile(r'<span class="tag"[^>]*>([^<]*)</span>')

    LINE = re.compile(r'(?s)<a class="more sort-button pull-right"[^>]*>.*?'
                      r'<h3 class="title">\s*(.*?)\s*</h3>')
    EP = re.compile(r'<a class="btn btn-default"\s+href="(/vod/play/id/(\d+)/sid/(\d+)/nid/(\d+)\.html)"'
                    r'[^>]*>([^<]*)</a>')
    PLAY_DATA = re.compile(r'player_data\s*=\s*(\{.*?\})\s*</script>', re.S)

    # ================= 基础 =================

    def getName(self):
        return "TVB云播"

    def init(self, extend=""):
        host = (extend or "").strip()
        if not host:
            host = self.DEFAULT_HOST
        if not host.startswith("http"):
            host = "http://" + host
        self.host = host.rstrip("/")
        self._ck, self._ck_ts = "", 0.0
        self._parse = {}

    def isVideoFormat(self, url):
        return True if re.search(r"\.(m3u8|mp4|flv)(\?|$)", url or "") else False

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ================= HTTP（含 WAF 自动解算） =================

    def _raw(self, url, cookie=None, referer=None, timeout=20):
        """返回响应对象；兼容各版本 self.fetch 的参数签名差异。"""
        h = {
            "User-Agent": self.UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if referer:
            h["Referer"] = referer
        if cookie:
            h["Cookie"] = cookie
        for kw in ({"headers": h, "timeout": timeout, "allow_redirects": True},
                   {"headers": h, "timeout": timeout},
                   {"headers": h}):
            try:
                return self.fetch(url, **kw)
            except TypeError:
                continue
            except Exception:
                return None
        return None

    @staticmethod
    def _resp_text(r):
        if r is None:
            return ""
        try:
            t = r.text
            if t:
                return t
        except Exception:
            pass
        try:
            return (r.content or b"").decode("utf-8", "ignore")
        except Exception:
            return ""

    @staticmethod
    def _resp_setcookie(r, name):
        """从响应里挑出 Set-Cookie 中 <name> 的值；不同宿主的 headers 类型差异很大。"""
        hs = getattr(r, "headers", None)
        cands = []
        try:
            if hasattr(hs, "items"):
                for k, v in hs.items():
                    if str(k).lower() in ("set-cookie", "set-cookie2"):
                        cands.append(v if isinstance(v, str) else str(v))
        except Exception:
            pass
        try:
            ga = getattr(hs, "get_all", None)
            if callable(ga):
                cands += [str(x) for x in (ga("Set-Cookie") or [])]
        except Exception:
            pass
        try:                                     # 有的宿主把 cookie 单独挂在 resp.cookies
            ck = getattr(r, "cookies", None)
            if isinstance(ck, dict) and ck.get(name):
                return str(ck[name])
        except Exception:
            pass
        for c in cands:
            for part in str(c).split(","):
                mm = re.match(r"\s*([^=;]+)=([^;]+)", part)
                if mm and mm.group(1).strip() == name:
                    return mm.group(2).strip()
        m = re.search(re.escape(name) + r"=([^;\s,]+)", " ".join(cands))
        return m.group(1) if m else ""

    def _solve_waf(self):
        """解算滑动验证 → 返回 'name=value'，失败返回空串。"""
        html = self._resp_text(self._raw(self.host + "/"))
        m = re.search(r'src="(/huadong_[^"]+\.js[^"]*)"', html)
        if not m:
            return ""                     # 没被拦（cookie 还有效 / IP 放行）
        js = self._resp_text(self._raw(self.host + m.group(1), referer=self.host + "/"))
        mk = re.search(r'key="([0-9a-fA-F]{16,})"', js)
        mv = re.search(r'value="([0-9a-fA-F]{16,})"', js)
        if not (mk and mv):
            return ""
        key, value = mk.group(1), mv.group(1)
        # JS: stringtoHex 里 charCodeAt() 无参取首字符码，parseInt(码) 是空操作 → 逐字符 +1 拼接
        ans = hashlib.md5("".join(str(ord(c) + 1) for c in value).encode()).hexdigest()
        mp = re.search(r'get\("(/[^"]*?_yanzheng_huadong\.php\?[^"]*?key=)"', js)
        if not mp:
            return ""
        r = self._raw(self.host + mp.group(1) + key + "&value=" + ans, referer=self.host + "/")
        name = self._resp_text(r).strip()
        if not name:
            return ""
        val = self._resp_setcookie(r, name)
        return ("%s=%s" % (name, val)) if val else ""

    def _cookie(self):
        if self._ck and time.time() - self._ck_ts < self.WAF_TTL:
            return self._ck
        ck = self._solve_waf()
        if ck:
            self._ck, self._ck_ts = ck, time.time()
        return ck or self._ck

    def _text(self, url, referer=None, tries=3):
        out = ""
        for _ in range(tries):
            ck = self._cookie()
            t = self._resp_text(self._raw(url, cookie=ck, referer=referer or self.host + "/"))
            if t and "slideBox" not in t and "滑动验证" not in t:
                return t
            out = t or out
            self._ck, self._ck_ts = "", 0.0        # 失效 → 下一轮重新解算
            time.sleep(0.3)
        return "" if ("slideBox" in out or "滑动验证" in out) else out

    # ================= 列表 =================

    @staticmethod
    def _unesc(s):
        if not s:
            return ""
        return (s.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
                 .replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " "))

    @staticmethod
    def _clean(s):
        return re.sub(r"\s+", " ", (s or "")).strip()

    def _cards(self, html):
        """首页 / 分类页 / 搜索页 共用一个卡片提取器（三处卡片 DOM 同构，只是容器不同）。"""
        out, seen = [], set()
        # 首页有 11 个 ul.myui-vodlist 区块（含轮播、榜单等），只收「真有详情链」的主列表区块
        blocks = [b for b in self.LIST_UL.findall(html or "")
                  if b.count("/vod/detail/id/") >= 8]
        if not blocks:
            i = (html or "").find('id="searchList"')        # 搜索页用的是 myui-vodlist__media
            if i >= 0:
                j = html.find("</ul>", i)
                blocks = [html[i:j if j > 0 else len(html)]]
        for blk in blocks:
            for m in re.finditer(r'(?s)<li[^>]*>(.*?)(?=<li[^>]*>|$)', blk):
                seg = m.group(1)
                mid = self.CARD_ID.search(seg)
                if not mid:
                    continue
                vid = mid.group(1)
                if vid in seen:
                    continue
                mt = self.CARD_TITLE.search(seg)
                name = self._unesc(mt.group(1)) if mt else ""
                if not name:
                    mt = re.search(r'<h4[^>]*>.*?>([^<]+)</a>', seg, re.S)
                    name = self._unesc(mt.group(1)) if mt else ""
                if not name:
                    continue
                mp = self.CARD_PIC.search(seg)
                mrem = self.CARD_REM.search(seg)
                seen.add(vid)
                out.append({
                    "vod_id": vid,
                    "vod_name": self._clean(name),
                    "vod_pic": self._unesc(mp.group(1) if mp else ""),
                    "vod_remarks": self._clean(self._unesc(mrem.group(1))) if mrem else "",
                })
        return out

    def homeContent(self, filter):
        return {"class": [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "剧集"},
            {"type_id": "3", "type_name": "综艺"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "5", "type_name": "短剧"},
            {"type_id": "13", "type_name": "国产剧"},
            {"type_id": "14", "type_name": "港台剧"},
            {"type_id": "15", "type_name": "日韩剧"},
            {"type_id": "16", "type_name": "欧美剧"},
            {"type_id": "20", "type_name": "海外剧"},
            {"type_id": "6", "type_name": "动作片"},
            {"type_id": "7", "type_name": "喜剧片"},
            {"type_id": "8", "type_name": "爱情片"},
            {"type_id": "9", "type_name": "科幻片"},
            {"type_id": "10", "type_name": "剧情片"},
            {"type_id": "11", "type_name": "恐怖片"},
            {"type_id": "12", "type_name": "战争片"},
            {"type_id": "21", "type_name": "大陆综艺"},
            {"type_id": "22", "type_name": "香港综艺"},
            {"type_id": "23", "type_name": "日韩综艺"},
        ]}

    def homeVideoContent(self):
        return {"list": self._cards(self._text(self.host + "/"))}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        url = ("%s/vod/type/id/%s.html" % (self.host, tid) if pg == 1
               else "%s/vod/type/id/%s/page/%d.html" % (self.host, tid, pg))
        lst = self._cards(self._text(url))
        return {"list": lst, "page": pg, "pagecount": 9999,
                "limit": len(lst) or 48, "total": 999999}

    def searchContent(self, key, quick, pg=1):
        key = self._clean(key)
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if not key or pg > 1:                       # 站点搜索无翻页（第 2 页重复第 1 页）
            return {"list": [], "page": pg}
        url = self.host + "/vod/search/wd/" + urllib.parse.quote(key, safe="") + ".html"
        return {"list": self._cards(self._text(url)), "page": pg}

    # ================= 详情 =================

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = str(vid).strip().strip("/").split("/")[-1]
        d = self._detail(vid)
        return {"list": [d]} if d else {"list": []}

    def _detail(self, vid):
        page_url = "%s/vod/detail/id/%s.html" % (self.host, vid)
        html = self._text(page_url)
        if not html:
            return None
        i = html.find('<div class="myui-content__detail">')
        seg = html[i:i + 14000] if i >= 0 else html[:14000]

        def one(pat, src=None, g=1):
            m = re.search(pat, src if src is not None else seg, re.S)
            return self._clean(self._unesc(m.group(g))) if m else ""

        def strip_tags(s):
            s = re.sub(r"<[^>]+>", " ", s or "")
            return self._clean(self._unesc(s))

        name = one(r'<h1 class="title">([^<]+)</h1>', html) or one(r"<h1[^>]*>([^<]+)</h1>", html)
        pic = ""
        m = re.search(r'(?s)<div class="myui-content__thumb">.*?data-original="([^"]+)"', html)
        if m:
            pic = self._unesc(m.group(1))
        content = strip_tags(one(r'<span class="data" style="display: none;"><p>(.*?)</p></span>'))
        if not content:                                  # 电影页没有「完整版」块
            content = strip_tags(one(r'class="sketch content">(.*?)</span>'))

        lines, froms, urls = self._lines(html)
        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "vod_content": content,
            "vod_actor": strip_tags(one(r'主演：</span>(.*?)</p>')),
            "vod_director": strip_tags(one(r'导演：</span>(.*?)</p>')),
            "vod_area": one(r'地区：</span><a[^>]*>([^<]+)</a>') or one(r'地区：</span>([^<]+?)<'),
            "vod_year": one(r'年份：</span><a[^>]*>([^<]+)</a>') or one(r'年份：</span>([^<]+?)<'),
            "type_name": one(r'分类：</span><a[^>]*>([^<]+)</a>'),
            "vod_remarks": one(r'更新：</span><span[^>]*>([^<]+)</span>'),
            "vod_play_from": "$$$".join(froms),
            "vod_play_url": "$$$".join(urls),
        }

    def _lines(self, html):
        """线路名与剧集都从页面里成对切出来（线路顺序 = 页面顺序，不按 sid 排）。"""
        froms, urls = [], []
        for m in self.LINE.finditer(html):
            nm = self._clean(m.group(1)) or ("线路%d" % (len(froms) + 1))
            ul = html.find('<ul class="myui-content__list', m.end())
            if ul < 0:
                continue
            end = html.find("</ul>", ul)
            blk = html[ul:end if end > 0 else len(html)]
            eps = []
            for e in self.EP.finditer(blk):
                vid, sid, nid = e.group(2), e.group(3), e.group(4)
                ep = self._clean(self._unesc(e.group(5))) or ("第%d集" % (len(eps) + 1))
                eps.append("%s$%s|%s|%s" % (ep, vid, sid, nid))
            if not eps:
                continue
            froms.append(nm)
            urls.append("#".join(eps))
        return None, froms, urls

    # ================= 播放 =================

    @staticmethod
    def _unesc_js(s):
        """把 JS 字面量里的 \\u0026 / \\/ 还原成可用的 URL。"""
        if not s:
            return ""
        s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
        return s.replace("\\/", "/").strip()

    @staticmethod
    def _enc_url(u):
        """中文文件名必须转义后才能被播放器直接请求（实测未转义会 404）。"""
        if not u or all(ord(c) < 128 for c in u):
            return u
        try:
            return urllib.parse.quote(u, safe=":/?&=#%+~!$'()*,;@[]")
        except Exception:
            return u

    def _parsers(self):
        if self._parse:
            return self._parse
        js = self._text(self.host + "/static/js/playerconfig.js")
        mp = dict(self.PARSE_MAP)
        m = re.search(r'MacPlayerConfig\.player_list\s*=\s*(\{.*?\})\s*;', js or "", re.S)
        if m:
            try:
                d = json.loads(m.group(1))
                for k, v in (d or {}).items():
                    pu = (v or {}).get("parse") or ""
                    if pu:
                        mp[k] = pu.replace("\\/", "/")
            except Exception:
                pass
        self._parse = mp
        return mp

    def playerContent(self, flag, id, vipFlags):
        raw = (id or "").strip()
        parts = raw.split("|")
        if len(parts) != 3:
            return {"parse": 1, "url": self.host + "/"}
        vodid, sid, nid = parts
        page_url = "%s/vod/play/id/%s/sid/%s/nid/%s.html" % (self.host, vodid, sid, nid)
        fallback = {"parse": 1, "url": page_url, "header": {"User-Agent": self.UA,
                                                            "Referer": self.host + "/"}}
        html = self._text(page_url)
        m = self.PLAY_DATA.search(html or "")
        if not m:
            return fallback
        try:
            d = json.loads(m.group(1))
        except Exception:
            return fallback

        url = self._unesc_js(str(d.get("url") or ""))
        frm = str(d.get("from") or "")
        enc = str(d.get("encrypt") or "0")
        url = self._decrypt(url, enc)
        if not url:
            return fallback

        if not url.startswith("http"):          # token 型线路 → 用站点自己的解析接口换直链
            pu = self._parsers().get(frm) or ""
            if pu:
                real = self._parse_play(pu + urllib.parse.quote(url, safe=""), page_url)
                if real:
                    url = real
        if not url.startswith("http"):
            return fallback
        return {"parse": 0, "url": self._enc_url(url),
                "header": {"User-Agent": self.UA, "Referer": self.host + "/"}}

    @staticmethod
    def _decrypt(url, enc):
        """player.js 的 url 加密方式：1=unescape，2=base64+unescape。"""
        if not url:
            return ""
        try:
            if enc == "1":
                return urllib.parse.unquote(url)
            if enc == "2":
                import base64
                raw = base64.b64decode(url + "=" * (-len(url) % 4))
                return urllib.parse.unquote(raw.decode("utf-8", "ignore"))
        except Exception:
            return ""
        return url

    def _parse_play(self, api_url, referer):
        """解析接口返回的是一个播放器页，里面写着 var playUrl="真实地址"。"""
        t = self._text(api_url, referer=referer, tries=2)
        m = re.search(r'var\s+playUrl\s*=\s*"([^"]+)"', t or "")
        if not m:
            m = re.search(r'"url"\s*:\s*"(https?://[^"]+)"', t or "")
        return self._unesc_js(m.group(1)) if m else ""

    # ================= 本地代理（源站直链，无需代理） =================

    def localProxy(self, param):
        return None
